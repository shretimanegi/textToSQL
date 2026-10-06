import pytest_asyncio

from app.db import close_pools, open_pools


@pytest_asyncio.fixture(scope="session", autouse=True)
async def pools():
    await open_pools()
    yield
    await close_pools()
