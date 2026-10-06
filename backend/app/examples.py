"""F3 few-shot retrieval: the top-k most similar verified question->SQL pairs."""

from app import embeddings
from app.db import admin_pool

TOP_K_EXAMPLES = 3


async def retrieve_examples(question: str, k: int = TOP_K_EXAMPLES) -> list[dict]:
    [vec] = await embeddings.embed([question], task="RETRIEVAL_QUERY")
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, db_id, question, evidence, sql, embedding <=> %s::vector AS dist FROM app.examples"
            " WHERE verified AND embedding IS NOT NULL ORDER BY dist LIMIT %s",
            (embeddings.to_pgvector(vec), k))
        rows = await cur.fetchall()
    return [{"id": i, "db_id": d, "question": q, "evidence": e, "sql": s, "distance": float(dist)}
            for i, d, q, e, s, dist in rows]


def render_examples(examples: list[dict]) -> str:
    """Prompt block. Examples come from other databases, so the model is told to copy style, not names."""
    if not examples:
        return ""
    blocks = []
    for ex in examples:
        hint = f"\nHint: {ex['evidence']}" if ex.get("evidence") else ""
        blocks.append(f"Question: {ex['question']}{hint}\nSQL: {ex['sql']}")
    return ("Examples of solved questions (they use OTHER databases: follow their SQL style and "
            "PostgreSQL dialect, but only use tables and columns from the schema above):\n\n" + "\n\n".join(blocks))
