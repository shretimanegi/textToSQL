"""Run validated SQL as a read-only role inside BEGIN READ ONLY ... ROLLBACK (layers 1, 3, 4)."""

from dataclasses import dataclass
from typing import Any

from psycopg import sql as psql

from app.config import settings
from app.db import eval_pool, readonly_pool
from app.safety import DEFAULT_SCHEMA, MAX_ROWS, validate_sql


@dataclass
class QueryResult:
    sql: str  # the SQL actually executed (validated, LIMIT-capped)
    columns: list[str]
    rows: list[list[Any]]


async def execute_sql(
    sql: str,
    schema: str = DEFAULT_SCHEMA,
    max_rows: int = MAX_ROWS,
    timeout_s: int | None = None,
    explain_first: bool = False,
) -> QueryResult:
    """Validate, then execute. Raises UnsafeSQL or a psycopg error.

    The product schema `data` runs as readonly_user; any other schema (BIRD eval) runs as
    eval_readonly, so readonly_user's grants never widen beyond `data`.
    """
    safe_sql = validate_sql(sql, schema=schema, max_rows=max_rows)
    pool = readonly_pool if schema == DEFAULT_SCHEMA else eval_pool
    timeout = timeout_s or settings.query_timeout_s
    async with pool.connection() as conn:
        await conn.execute("BEGIN READ ONLY")
        try:
            await conn.execute(f"SET LOCAL statement_timeout = '{int(timeout)}s'")
            if schema != DEFAULT_SCHEMA:
                await conn.execute(psql.SQL("SET LOCAL search_path = {}").format(psql.Identifier(schema)))
            if explain_first:  # cheap: surfaces unknown columns/types without running the query
                await conn.execute("EXPLAIN " + safe_sql)
            cur = await conn.execute(safe_sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = [list(r) for r in await cur.fetchall()] if cur.description else []
        finally:
            await conn.execute("ROLLBACK")
    return QueryResult(sql=safe_sql, columns=columns, rows=rows)
