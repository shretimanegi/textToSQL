"""F10: a thumbs-up on a query that ran fine becomes a verified few-shot example."""

import logging

from app import embeddings
from app.db import admin_pool

log = logging.getLogger(__name__)
PRODUCT_DB = "chinook"


async def promote_to_example(query_id: int) -> bool:
    """Save (question, final_sql) of an answered query to app.examples. True if a new example was stored.

    Only queries that ran successfully through the safety layer qualify (final_sql is set only for those),
    and the same pair is never stored twice. Embedding failures never lose the feedback itself.
    """
    async with admin_pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT question, final_sql, status FROM app.query_log WHERE id = %s", (query_id,))).fetchone()
        if not row or row[2] != "ok" or not row[1]:
            return False
        question, sql = row[0], row[1]
        if await (await conn.execute(
                "SELECT 1 FROM app.examples WHERE source = 'user' AND question = %s AND sql = %s",
                (question, sql))).fetchone():
            return False
    try:
        [vec] = await embeddings.embed([question])
    except Exception:
        log.exception("could not embed feedback example for query %s", query_id)
        return False
    async with admin_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app.examples (db_id, question, sql, verified, source, embedding)"
            " VALUES (%s, %s, %s, TRUE, 'user', %s::vector)",
            (PRODUCT_DB, question, sql, embeddings.to_pgvector(vec)))
    return True
