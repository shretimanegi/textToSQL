"""Seed app.examples with BIRD *train* question->SQL pairs (never dev, so no leakage into the eval).

    uv run python -m app.seed_examples

Train SQL is SQLite; it is translated to PostgreSQL with sqlglot and all identifiers are quoted.
Train databases are disjoint from the dev databases, so these are cross-domain examples.
"""

import asyncio
import json
from pathlib import Path

import sqlglot

from app import embeddings
from app.db import admin_pool, close_pools, open_pools
from app.db_setup import ensure_schema

ROOT = Path(__file__).resolve().parents[1] / "eval" / "data"
TRAIN_JSON = ROOT / "train" / "train.json"
DEV_JSON = ROOT / "bird" / "dev_20240627" / "dev.json"


def to_postgres(sqlite_sql: str) -> str | None:
    try:
        return sqlglot.parse_one(sqlite_sql, read="sqlite").sql(dialect="postgres", identify=True)
    except sqlglot.errors.SqlglotError:
        return None


def load_seed_rows() -> tuple[list[dict], dict]:
    train = json.loads(TRAIN_JSON.read_text())
    dev_questions = {q["question"].strip().lower() for q in json.loads(DEV_JSON.read_text())}
    rows, stats = [], {"train": len(train), "leaked_dropped": 0, "untranslatable": 0}
    for ex in train:
        if ex["question"].strip().lower() in dev_questions:
            stats["leaked_dropped"] += 1
            continue
        pg = to_postgres(ex["SQL"])
        if pg is None:
            stats["untranslatable"] += 1
            continue
        rows.append({"db_id": ex["db_id"], "question": ex["question"].strip(),
                     "evidence": (ex.get("evidence") or "").strip() or None, "sql": pg})
    stats["seeded"] = len(rows)
    return rows, stats


async def main() -> None:
    rows, stats = load_seed_rows()
    vectors = await embeddings.embed([r["question"] for r in rows])
    await open_pools()
    try:
        await ensure_schema()
        async with admin_pool.connection() as conn:
            await conn.execute("DELETE FROM app.examples WHERE source = 'seed'")
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO app.examples (db_id, question, evidence, sql, verified, source, embedding)"
                    " VALUES (%s, %s, %s, %s, TRUE, 'seed', %s::vector)",
                    [(r["db_id"], r["question"], r["evidence"], r["sql"], embeddings.to_pgvector(v))
                     for r, v in zip(rows, vectors)])
    finally:
        await close_pools()
    print(stats)


if __name__ == "__main__":
    asyncio.run(main())
