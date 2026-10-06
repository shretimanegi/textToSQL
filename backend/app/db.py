"""Two pools: `readonly` runs generated SQL; `admin` serves the app schema and introspection."""

from psycopg_pool import AsyncConnectionPool

from app.config import settings

readonly_pool = AsyncConnectionPool(
    settings.readonly_database_url, min_size=1, max_size=5, open=False, kwargs={"autocommit": True, "prepare_threshold": None}
)
admin_pool = AsyncConnectionPool(
    settings.admin_database_url, min_size=1, max_size=5, open=False, kwargs={"autocommit": True, "prepare_threshold": None}
)
eval_pool = AsyncConnectionPool(
    settings.eval_database_url or settings.readonly_database_url,
    min_size=1, max_size=8, open=False, kwargs={"autocommit": True, "prepare_threshold": None},
)


async def open_pools() -> None:
    await readonly_pool.open(wait=True)
    await admin_pool.open(wait=True)
    await eval_pool.open(wait=True)


async def close_pools() -> None:
    await readonly_pool.close()
    await admin_pool.close()
    await eval_pool.close()
