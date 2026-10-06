"""DB-level layers, exercised WITHOUT the parser (readonly_pool directly) to prove independence."""

import time

import psycopg
import pytest

from app.db import admin_pool, readonly_pool
from app.executor import execute_sql


async def test_select_works_and_is_capped():
    r = await execute_sql("SELECT * FROM data.track")
    assert len(r.rows) == 500 and "track_id" in r.columns


async def test_row_values_and_columns():
    r = await execute_sql("SELECT count(*) AS n FROM data.album")
    assert r.columns == ["n"] and r.rows[0][0] == 347


async def test_chinook_has_11_tables():
    async with admin_pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='data'")
        assert (await cur.fetchone())[0] == 11


@pytest.mark.parametrize("sql", [
    "DELETE FROM data.album",
    "UPDATE data.artist SET name = 'x'",
    "DROP TABLE data.album",
    "CREATE TABLE data.evil (id int)",
    "INSERT INTO data.genre (genre_id, name) VALUES (999, 'x')",
])
async def test_role_cannot_write(sql):
    async with readonly_pool.connection() as conn:
        with pytest.raises(psycopg.errors.Error):
            await conn.execute(sql)


@pytest.mark.parametrize("table", ["app.query_log", "app.examples", "app.schema_docs", "app.feedback", "app.eval_runs"])
async def test_role_cannot_read_app_schema(table):
    async with readonly_pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute(f"SELECT * FROM {table}")


async def test_role_cannot_create_in_public():
    async with readonly_pool.connection() as conn:
        with pytest.raises(psycopg.errors.Error):
            await conn.execute("CREATE TABLE public.evil (id int)")


async def test_read_only_transaction_blocks_writes_even_if_role_could():
    """Layer 4 alone: an admin connection inside BEGIN READ ONLY still cannot write."""
    async with admin_pool.connection() as conn:
        await conn.execute("BEGIN READ ONLY")
        try:
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                await conn.execute("DELETE FROM data.album")
        finally:
            await conn.execute("ROLLBACK")


async def test_timeout_enforced_at_db_level_without_parser():
    async with readonly_pool.connection() as conn:
        start = time.monotonic()
        with pytest.raises(psycopg.errors.QueryCanceled):
            await conn.execute("SELECT pg_sleep(30)")
        assert time.monotonic() - start < 7


async def test_expensive_query_times_out_via_executor(monkeypatch):
    """A legal SELECT that is simply too slow is cancelled at ~5s."""
    start = time.monotonic()
    with pytest.raises(psycopg.errors.QueryCanceled):
        await execute_sql(
            "SELECT count(*) FROM generate_series(1, 100000000) a, generate_series(1, 100000000) b"
        )
    assert time.monotonic() - start < 8


async def test_connection_usable_after_error():
    with pytest.raises(psycopg.Error):
        await execute_sql("SELECT * FROM data.no_such_table")
    r = await execute_sql("SELECT 1 AS x")
    assert r.rows == [[1]]


async def test_data_unchanged_after_attacks():
    async with admin_pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) FROM data.album")
        assert (await cur.fetchone())[0] == 347
