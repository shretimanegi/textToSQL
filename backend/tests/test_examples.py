import json

import pytest

from app import examples
from app.db import admin_pool
from app.seed_examples import DEV_JSON, TRAIN_JSON, to_postgres

needs_seed = pytest.mark.skipif(not TRAIN_JSON.exists(), reason="BIRD train.json not downloaded")


def test_to_postgres_translates_and_quotes():
    out = to_postgres("SELECT `Free Meal Count (K-12)` FROM frpm WHERE `County Name` = 'Alameda' LIMIT 1")
    assert '"Free Meal Count (K-12)"' in out and "`" not in out


def test_to_postgres_returns_none_on_garbage():
    assert to_postgres("SELEC FROM ((") is None


def test_render_examples_empty_and_filled():
    assert examples.render_examples([]) == ""
    text = examples.render_examples([{"question": "How many?", "evidence": "h", "sql": "SELECT 1"}])
    assert "OTHER databases" in text and "Question: How many?" in text and "Hint: h" in text and "SQL: SELECT 1" in text


@needs_seed
def test_no_train_question_appears_in_dev():
    dev = {q["question"].strip().lower() for q in json.loads(DEV_JSON.read_text())}
    train = json.loads(TRAIN_JSON.read_text())
    assert not [t for t in train if t["question"].strip().lower() in dev]


@needs_seed
def test_train_and_dev_databases_are_disjoint():
    dev = {q["db_id"] for q in json.loads(DEV_JSON.read_text())}
    assert not dev & {t["db_id"] for t in json.loads(TRAIN_JSON.read_text())}


async def _n_seed() -> int:
    async with admin_pool.connection() as conn:
        return (await (await conn.execute("SELECT count(*) FROM app.examples WHERE source='seed'")).fetchone())[0]


async def test_retrieve_top3_ordered_and_relevant():
    if await _n_seed() == 0:
        pytest.skip("run `python -m app.seed_examples` first")
    exs = await examples.retrieve_examples("How many movies were released in 1945?")
    assert len(exs) == 3
    dists = [e["distance"] for e in exs]
    assert dists == sorted(dists)
    assert all(e["sql"].strip().upper().startswith(("SELECT", "WITH")) for e in exs)


async def test_seeded_rows_have_embeddings_and_are_verified():
    if await _n_seed() == 0:
        pytest.skip("run `python -m app.seed_examples` first")
    async with admin_pool.connection() as conn:
        bad = (await (await conn.execute(
            "SELECT count(*) FROM app.examples WHERE source='seed' AND (embedding IS NULL OR NOT verified)")).fetchone())[0]
    assert bad == 0


async def test_unverified_examples_are_never_retrieved():
    async with admin_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app.examples (db_id, question, sql, verified, source, embedding)"
            " SELECT 'zz', 'zzz unverified probe', 'SELECT 1', FALSE, 'user', embedding FROM app.examples LIMIT 1")
        try:
            exs = await examples.retrieve_examples("zzz unverified probe", k=50)
            assert all(e["db_id"] != "zz" for e in exs)
        finally:
            await conn.execute("DELETE FROM app.examples WHERE db_id = 'zz'")
