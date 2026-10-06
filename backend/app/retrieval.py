"""F2 schema retrieval: embed the question, take the top-k columns, expand to tables."""

from dataclasses import dataclass

from app import baseline, embeddings
from app.db import admin_pool

TOP_K_COLUMNS = 15


@dataclass
class Retrieved:
    tables: set[str]
    columns: list[tuple[str, str, float]]  # (table, column, cosine distance), best first


def expand_tables(hit_tables: set[str], structure: dict) -> set[str]:
    """Hit tables plus bridge tables, so joins between hit tables stay possible.

    A bridge is a table that foreign-keys into (or is referenced by) at least two hit tables
    without being one itself, e.g. `disp` linking `account` and `client`.
    """
    neighbours: dict[str, set[str]] = {}
    for name, t in structure.items():
        for fk in t["fks"]:
            neighbours.setdefault(name, set()).add(fk["ref_table"])
            neighbours.setdefault(fk["ref_table"], set()).add(name)
        for definition in t["raw_fks"]:  # Chinook: FKs come from pg_get_constraintdef text
            ref = definition.split("REFERENCES", 1)[1].strip().split("(")[0].split(".")[-1].strip('"')
            neighbours.setdefault(name, set()).add(ref)
            neighbours.setdefault(ref, set()).add(name)
    bridges = {t for t, n in neighbours.items() if t not in hit_tables and len(n & hit_tables) >= 2}
    return hit_tables | bridges


async def retrieve(db_key: str, schema: str, query_text: str, k: int = TOP_K_COLUMNS) -> Retrieved:
    [vec] = await embeddings.embed([query_text], task="RETRIEVAL_QUERY")
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT table_name, column_name, embedding <=> %s::vector AS dist FROM app.schema_docs"
            " WHERE db_id = %s ORDER BY dist LIMIT %s",
            (embeddings.to_pgvector(vec), db_key, k))
        hits = [(t, c, float(d)) for t, c, d in await cur.fetchall()]
    structure = await baseline.get_schema(schema)
    return Retrieved(tables=expand_tables({t for t, _, _ in hits}, structure), columns=hits)
