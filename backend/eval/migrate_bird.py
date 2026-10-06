"""One-time migration of the 11 BIRD dev SQLite databases into Postgres, one schema each.

    uv run python -m eval.migrate_bird

Idempotent: each bird_<db_id> schema is dropped and rebuilt. Original table and column
names are kept (quoted), since BIRD questions and gold SQL use them verbatim.
"""

import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql as psql

from app.config import settings

DATA = Path(__file__).parent / "data" / "bird"
DB_DIR = DATA / "dbs" / "dev_databases"
REPORT = Path(__file__).parent / "data" / "migration_report.json"
FK_META = Path(__file__).parent / "data" / "bird_fks.json"

EVAL_ROLE = "eval_readonly"


def schema_name(db_id: str) -> str:
    return f"bird_{db_id}"


def declared_pg_type(decl: str) -> str:
    d = (decl or "").upper()
    if "INT" in d:
        return "BIGINT"
    if any(k in d for k in ("REAL", "FLOA", "DOUB", "DECIMAL", "NUMERIC")):
        return "DOUBLE PRECISION"
    return "TEXT"


def fits(pg_type: str, values: list) -> bool:
    """Do all non-null values survive in this column type? SQLite is loosely typed, Postgres is not."""
    if pg_type == "BIGINT":
        return all(isinstance(v, int) and -(2**63) <= v < 2**63 for v in values if v is not None)
    if pg_type == "DOUBLE PRECISION":
        return all(isinstance(v, (int, float)) for v in values if v is not None)
    return True


def to_text(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", errors="replace")
    return str(v).replace("\x00", "")


def ident(name: str) -> psql.Identifier:
    return psql.Identifier(name)


def migrate_db(pg: psycopg.Connection, db_id: str) -> dict:
    schema = schema_name(db_id)
    src = sqlite3.connect(f"file:{DB_DIR / db_id / (db_id + '.sqlite')}?mode=ro", uri=True)
    src.text_factory = lambda b: b.decode("utf-8", errors="replace")

    pg.execute(psql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(ident(schema)))
    pg.execute(psql.SQL("CREATE SCHEMA {}").format(ident(schema)))

    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    report = {"tables": {}, "skipped_pk": [], "skipped_fk": [], "text_fallbacks": []}

    pk_cols: dict[str, list[str]] = {}
    table_cols: dict[str, list[str]] = {}
    for t in tables:
        info = src.execute(f'PRAGMA table_info("{t}")').fetchall()  # cid, name, type, notnull, dflt, pk
        cols = [r[1] for r in info]
        table_cols[t] = cols
        pk_cols[t] = [r[1] for r in sorted((r for r in info if r[5] > 0), key=lambda r: r[5])]
        rows = src.execute(f'SELECT * FROM "{t}"').fetchall()

        types = []
        for i, r in enumerate(info):
            pg_type = declared_pg_type(r[2])
            if not fits(pg_type, [row[i] for row in rows]):
                report["text_fallbacks"].append(f"{t}.{r[1]} ({r[2]} -> TEXT)")
                pg_type = "TEXT"
            types.append(pg_type)

        coldefs = psql.SQL(", ").join(
            psql.SQL("{} {}").format(ident(c), psql.SQL(ty)) for c, ty in zip(cols, types))
        pg.execute(psql.SQL("CREATE TABLE {}.{} ({})").format(ident(schema), ident(t), coldefs))

        with pg.cursor() as cur, cur.copy(
            psql.SQL("COPY {}.{} FROM STDIN").format(ident(schema), ident(t))
        ) as cp:
            for row in rows:
                cp.write_row([to_text(v) if ty == "TEXT" else v for v, ty in zip(row, types)])

        report["tables"][t] = {"sqlite_rows": len(rows)}

    # Constraints after load so dirty data cannot block the load itself.
    for t in tables:
        if pk_cols[t]:
            try:
                pg.execute(psql.SQL("ALTER TABLE {}.{} ADD PRIMARY KEY ({})").format(
                    ident(schema), ident(t), psql.SQL(", ").join(ident(c) for c in pk_cols[t])))
            except psycopg.Error as e:
                report["skipped_pk"].append(f"{t}({', '.join(pk_cols[t])}): {str(e).splitlines()[0]}")

    def resolve(name: str, choices: list[str]) -> str:
        """SQLite matches identifiers case-insensitively; Postgres (quoted) does not."""
        return next((c for c in choices if c.lower() == name.lower()), name)

    report["fks"] = []
    for t in tables:
        fks: dict[int, list] = {}
        for fid, _seq, ref_table, frm, to, *_ in src.execute(f'PRAGMA foreign_key_list("{t}")'):
            fks.setdefault(fid, []).append((ref_table, frm, to))
        for parts in fks.values():
            ref_table = resolve(parts[0][0], tables)
            frm = [resolve(p[1], table_cols[t]) for p in parts]
            ref_cols = table_cols.get(ref_table, [])
            to = [resolve(p[2], ref_cols) if p[2] else c for p, c in zip(parts, pk_cols.get(ref_table, []) or frm)]
            report["fks"].append({"table": t, "columns": frm, "ref_table": ref_table, "ref_columns": to})
            try:
                # NOT VALID keeps the relationship without rejecting dirty rows.
                pg.execute(psql.SQL("ALTER TABLE {}.{} ADD FOREIGN KEY ({}) REFERENCES {}.{} ({}) NOT VALID").format(
                    ident(schema), ident(t), psql.SQL(", ").join(ident(c) for c in frm),
                    ident(schema), ident(ref_table), psql.SQL(", ").join(ident(c) for c in to)))
            except psycopg.Error as e:
                # Typically BIRD declares an FK on a non-unique column; metadata above still records it.
                report["skipped_fk"].append(f"{t}({', '.join(frm)}) -> {ref_table}: {str(e).splitlines()[0]}")

    pg.execute(psql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(ident(schema), ident(EVAL_ROLE)))
    pg.execute(psql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(ident(schema), ident(EVAL_ROLE)))

    # Verify row counts landed intact.
    for t in tables:
        n = pg.execute(psql.SQL("SELECT count(*) FROM {}.{}").format(ident(schema), ident(t))).fetchone()[0]
        report["tables"][t]["pg_rows"] = n
        report["tables"][t]["ok"] = n == report["tables"][t]["sqlite_rows"]
    pg.execute(psql.SQL("ANALYZE").format())
    src.close()
    return report


def ensure_role(pg: psycopg.Connection) -> None:
    password = urlparse(settings.eval_database_url).password
    if not password:
        sys.exit("EVAL_DATABASE_URL must be set in .env (user eval_readonly, with a password)")
    exists = pg.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (EVAL_ROLE,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    pg.execute(psql.SQL(verb + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
        ident(EVAL_ROLE), psql.Literal(password)))
    # Same layers as readonly_user. Eval gold queries raise the timeout per transaction.
    pg.execute(psql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(ident(EVAL_ROLE)))
    pg.execute(psql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(ident(EVAL_ROLE)))
    pg.execute(psql.SQL("REVOKE ALL ON SCHEMA app FROM {}").format(ident(EVAL_ROLE)))
    pg.execute(psql.SQL("REVOKE ALL ON SCHEMA data FROM {}").format(ident(EVAL_ROLE)))


def main() -> None:
    db_ids = sorted(p.name for p in DB_DIR.iterdir() if (p / f"{p.name}.sqlite").exists())
    if not db_ids:
        sys.exit(f"no BIRD databases under {DB_DIR}; download and unzip dev.zip first")
    report = {}
    with psycopg.connect(settings.admin_database_url, autocommit=True) as pg:
        ensure_role(pg)
        for db_id in db_ids:
            print(f"migrating {db_id} ...", flush=True)
            report[db_id] = migrate_db(pg, db_id)
            r = report[db_id]
            bad = [t for t, v in r["tables"].items() if not v["ok"]]
            print(f"  {len(r['tables'])} tables, row-count mismatches: {bad or 'none'}, "
                  f"text fallbacks: {len(r['text_fallbacks'])}, skipped PK: {len(r['skipped_pk'])}, "
                  f"skipped FK: {len(r['skipped_fk'])}", flush=True)
    FK_META.write_text(json.dumps({d: r.pop("fks") for d, r in report.items()}, indent=2))
    REPORT.write_text(json.dumps(report, indent=2))
    print(f"report written to {REPORT}; FK metadata to {FK_META}")


if __name__ == "__main__":
    main()
