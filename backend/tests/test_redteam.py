import pytest

from app import baseline, pipeline
from app.executor import execute_sql
from app.db import admin_pool
from app.safety import UnsafeSQL, validate_sql
from tests.redteam_cases import REDTEAM_QUESTIONS, REDTEAM_SQL


def test_redteam_suite_has_20_plus_cases():
    assert len(REDTEAM_SQL) >= 20 and len(REDTEAM_QUESTIONS) >= 5


@pytest.mark.parametrize("label,sql", REDTEAM_SQL, ids=[c[0] for c in REDTEAM_SQL])
def test_parser_blocks(label, sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


@pytest.mark.parametrize("label,sql", REDTEAM_SQL, ids=[c[0] for c in REDTEAM_SQL])
async def test_executor_blocks(label, sql):
    with pytest.raises(UnsafeSQL):
        await execute_sql(sql)


async def _counts():
    async with admin_pool.connection() as conn:
        a = (await (await conn.execute("SELECT count(*) FROM data.album")).fetchone())[0]
        c = (await (await conn.execute("SELECT count(*) FROM data.customer")).fetchone())[0]
    return a, c


@pytest.mark.parametrize("question,evil_sql", REDTEAM_QUESTIONS, ids=[q[0] for q in REDTEAM_QUESTIONS])
async def test_malicious_question_end_to_end(monkeypatch, question, evil_sql):
    """The 'LLM' obeys the attacker. The safety layer must still stop it and data stays intact."""
    async def obedient(system, user, max_tokens=1024):
        return evil_sql

    monkeypatch.setattr(pipeline.llm, "complete", obedient)
    before = await _counts()
    r = await pipeline.ask(question)
    assert r.status == "blocked"
    assert r.rows == []
    assert await _counts() == before
