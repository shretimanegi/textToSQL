"""Idempotent app-schema upgrades for volumes created before a column or dimension changed.

Fresh installs get the same shape from db/init/02_app_tables.sql.
"""

from app.config import settings
from app.db import admin_pool

TABLES = {"schema_docs": "schema_docs_embedding_idx", "examples": "examples_embedding_idx"}


async def ensure_schema() -> None:
    dim = settings.embedding_dim
    async with admin_pool.connection() as conn:
        await conn.execute("ALTER TABLE app.schema_docs ADD COLUMN IF NOT EXISTS db_id TEXT NOT NULL DEFAULT ''")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS schema_docs_col_uidx "
                           "ON app.schema_docs (db_id, table_name, column_name)")
        await conn.execute("ALTER TABLE app.examples ADD COLUMN IF NOT EXISTS db_id TEXT NOT NULL DEFAULT ''")
        await conn.execute("ALTER TABLE app.examples ADD COLUMN IF NOT EXISTS evidence TEXT")
        for table, index in TABLES.items():
            row = await (await conn.execute(
                "SELECT a.atttypmod FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attname = 'embedding'",
                (f"app.{table}",))).fetchone()
            if row[0] != dim:
                # Stored vectors belong to the old model and would be meaningless at the new size.
                await conn.execute(f"DROP INDEX IF EXISTS app.{index}")
                await conn.execute(f"UPDATE app.{table} SET embedding = NULL")
                await conn.execute(f"ALTER TABLE app.{table} ALTER COLUMN embedding TYPE vector({dim})")
                await conn.execute(f"CREATE INDEX {index} ON app.{table} USING hnsw (embedding vector_cosine_ops)")
