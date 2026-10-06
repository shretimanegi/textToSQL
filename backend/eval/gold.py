"""Translate BIRD gold SQL (SQLite) to Postgres and check which questions still run.

    uv run python -m eval.gold          # writes eval/data/gold_status.json

SQLite matches identifiers case-insensitively, Postgres (quoted) does not, so every
table/column in the gold AST is resolved against the real catalog before quoting.
"""

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import sqlglot
from sqlglot import exp

from app.db import admin_pool, close_pools, open_pools
from app.executor import execute_sql
from app.safety import UnsafeSQL
from eval.migrate_bird import DATA, schema_name

DEV_JSON = DATA / "dev_20240627" / "dev.json"
GOLD_STATUS = Path(__file__).parent / "data" / "gold_status.json"
GOLD_TIMEOUT_S = 30
NO_CAP = 10_000_000


def load_questions() -> list[dict]:
    return json.loads(DEV_JSON.read_text())


async def load_catalog() -> dict[str, dict[str, list[str]]]:
    """{db_id: {table: [columns]}} straight from Postgres."""
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns "
            "WHERE table_schema LIKE 'bird\\_%' ORDER BY table_schema, table_name, ordinal_position")
        rows = await cur.fetchall()
    cat: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for schema, table, col in rows:
        cat[schema.removeprefix("bird_")][table].append(col)
    return cat


def normalize(sql: str, tables: dict[str, list[str]], read: str) -> str:
    """Parse `sql` (dialect `read`), resolve table/column names case-insensitively against the
    catalog, and emit quoted PostgreSQL. This reproduces SQLite's case-insensitive identifier rules."""
    table_by_lower = {t.lower(): t for t in tables}
    col_spellings: dict[str, set[str]] = defaultdict(set)
    for cols in tables.values():
        for c in cols:
            col_spellings[c.lower()].add(c)

    tree = sqlglot.parse_one(sql, read=read)
    ctes = {c.alias.lower() for c in tree.find_all(exp.CTE)}
    for node in tree.walk():
        if isinstance(node, exp.Table) and isinstance(node.this, exp.Identifier):
            if node.name.lower() not in ctes and node.name.lower() in table_by_lower:
                node.this.set("this", table_by_lower[node.name.lower()])
        elif isinstance(node, exp.Column) and isinstance(node.this, exp.Identifier):
            spellings = col_spellings.get(node.name.lower())
            if spellings and node.name not in spellings:
                node.this.set("this", sorted(spellings)[0])
    return tree.sql(dialect="postgres", identify=True)


def translate(sql: str, tables: dict[str, list[str]]) -> str:
    """BIRD gold SQL (SQLite) -> Postgres."""
    return normalize(sql, tables, read="sqlite")


async def run_one(q: dict, catalog, sem: asyncio.Semaphore) -> dict:
    out = {"question_id": q["question_id"], "db_id": q["db_id"], "difficulty": q["difficulty"]}
    async with sem:
        try:
            pg_sql = translate(q["SQL"], catalog[q["db_id"]])
            out["sql_pg"] = pg_sql
            res = await execute_sql(pg_sql, schema=schema_name(q["db_id"]), max_rows=NO_CAP, timeout_s=GOLD_TIMEOUT_S)
            out.update(ok=True, n_rows=len(res.rows), error=None)
        except UnsafeSQL as e:
            out.update(ok=False, error=f"blocked: {e}")
        except Exception as e:  # translation or execution failure
            out.update(ok=False, error=f"{type(e).__name__}: {str(e).splitlines()[0][:200]}")
    return out


async def main() -> None:
    await open_pools()
    try:
        catalog = await load_catalog()
        questions = load_questions()
        sem = asyncio.Semaphore(6)
        results = await asyncio.gather(*(run_one(q, catalog, sem) for q in questions))
    finally:
        await close_pools()
    GOLD_STATUS.write_text(json.dumps(results, indent=1))
    ok = [r for r in results if r["ok"]]
    print(f"gold SQL runs on Postgres: {len(ok)}/{len(results)}")
    for diff in ("simple", "moderate", "challenging"):
        tot = [r for r in results if r["difficulty"] == diff]
        print(f"  {diff}: {sum(r['ok'] for r in tot)}/{len(tot)}")
    errs: dict[str, int] = defaultdict(int)
    for r in results:
        if not r["ok"]:
            errs[r["error"].split(":")[1].strip()[:70] if ":" in r["error"] else r["error"]] += 1
    for e, n in sorted(errs.items(), key=lambda x: -x[1])[:12]:
        print(f"  {n:4d}  {e}")


if __name__ == "__main__":
    asyncio.run(main())
