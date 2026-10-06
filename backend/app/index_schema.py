"""Build app.schema_docs: one LLM-written description + 3 sample values + embedding per column (F2).

    uv run python -m app.index_schema --all            # chinook + all 11 BIRD databases
    uv run python -m app.index_schema --db bird_financial

The LLM is called once per table (all of its columns in one prompt) rather than once per column,
to stay inside free-tier quotas; the output is still one description per column.
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from psycopg import sql as psql

from app import baseline, embeddings
from app.db import admin_pool, close_pools, open_pools
from app.db_setup import ensure_schema
from eval.cache import cached_complete

CACHE_DIR = Path(__file__).resolve().parents[1] / "eval" / "cache"

DESC_SYSTEM = """You document database columns for a text-to-SQL system.
Given a table's columns (name, type, sample values), write a short description of what each column means
(one sentence, at most 25 words; expand abbreviations and cryptic names, mention units/codes if the samples show them).
Reply with ONLY a JSON object mapping each column name exactly as given to its description."""


def db_key(schema: str) -> str:
    """Retrieval key stored in schema_docs.db_id."""
    return "chinook" if schema == "data" else schema.removeprefix("bird_")


async def sample_values(schema: str, table: str, column: str, n: int = 3) -> list[str]:
    q = psql.SQL("SELECT DISTINCT {c}::text FROM {s}.{t} WHERE {c} IS NOT NULL LIMIT {n}").format(
        c=psql.Identifier(column), s=psql.Identifier(schema), t=psql.Identifier(table), n=psql.Literal(n))
    async with admin_pool.connection() as conn:
        await conn.execute("SET statement_timeout = '20s'")
        rows = await (await conn.execute(q)).fetchall()
    return [r[0][:60] for r in rows]


async def describe_table(schema: str, table: str, columns: list[tuple[str, str]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    samples = {c: await sample_values(schema, table, c) for c, _ in columns}
    listing = "\n".join(f"- {c} ({t}); samples: {samples[c]}" for c, t in columns)
    resp = await cached_complete(DESC_SYSTEM, f"Table: {table}\nColumns:\n{listing}\n\nJSON:")
    desc: dict[str, str] = {}
    m = re.search(r"\{.*\}", resp["text"], re.DOTALL)
    if m:
        try:
            desc = {k: str(v) for k, v in json.loads(m.group(0)).items()}
        except json.JSONDecodeError:
            pass
    return desc, samples


def doc_text(table: str, column: str, typ: str, description: str, samples: list[str]) -> str:
    """The text that gets embedded. Table name is included so 'name' columns stay distinguishable."""
    ex = f" Examples: {', '.join(samples)}." if samples else ""
    return f"{table}.{column} ({typ}): {description}{ex}"


async def index_schema(schema: str) -> int:
    key = db_key(schema)
    structure = await baseline.get_schema(schema)
    rows = []  # (table, column, description, samples_str, text)
    for table, t in structure.items():
        desc, samples = await describe_table(schema, table, t["columns"])
        for col, typ in t["columns"]:
            d = desc.get(col) or f"{col.replace('_', ' ')} of {table}"
            rows.append((table, col, d, ", ".join(samples[col]), doc_text(table, col, typ, d, samples[col])))
    vectors = await embeddings.embed([r[4] for r in rows], task="RETRIEVAL_DOCUMENT")

    async with admin_pool.connection() as conn:
        await conn.execute("DELETE FROM app.schema_docs WHERE db_id = %s", (key,))
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO app.schema_docs (db_id, table_name, column_name, description, sample_values, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s::vector)",
                [(key, r[0], r[1], r[2], r[3], embeddings.to_pgvector(v)) for r, v in zip(rows, vectors)])
    return len(rows)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="schema name, e.g. data or bird_financial")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    embeddings.CACHE_DIR = CACHE_DIR  # only used by the optional Gemini provider
    await open_pools()
    try:
        await ensure_schema()
        if args.all:
            async with admin_pool.connection() as conn:
                rows = await (await conn.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname = 'data' OR nspname LIKE 'bird\\_%' ORDER BY 1")).fetchall()
            schemas = [r[0] for r in rows]
        elif args.db:
            schemas = [args.db]
        else:
            ap.error("pass --db NAME or --all")
        for s in schemas:
            n = await index_schema(s)
            print(f"indexed {s}: {n} columns", flush=True)
    finally:
        await close_pools()


if __name__ == "__main__":
    asyncio.run(main())
