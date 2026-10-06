import asyncio
import json

import pytest

from eval import harness
from eval.gold import load_catalog
from eval.migrate_bird import DATA, FK_META, REPORT, schema_name

pytestmark = pytest.mark.skipif(not REPORT.exists(), reason="BIRD not migrated (run eval.migrate_bird)")


def test_migration_row_counts_all_match():
    report = json.loads(REPORT.read_text())
    assert len(report) == 11
    for db, r in report.items():
        for t, v in r["tables"].items():
            assert v["ok"], f"{db}.{t}: {v}"


def test_fk_metadata_covers_all_databases():
    meta = json.loads(FK_META.read_text())
    assert len(meta) == 11 and sum(len(v) for v in meta.values()) > 100


def test_subset_is_fixed_200_and_all_gold_runnable():
    subset = harness.load_subset()
    assert len(subset) == 200 and len({q["question_id"] for q in subset}) == 200
    assert all(q["gold_sql_pg"] for q in subset)


async def test_eval_role_is_isolated():
    import psycopg
    from app.db import eval_pool
    async with eval_pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("SELECT * FROM app.query_log")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("SELECT * FROM data.album")
        with pytest.raises(psycopg.errors.Error):
            await conn.execute('DELETE FROM bird_financial."account"')


async def test_readonly_user_cannot_read_bird_schemas():
    import psycopg
    from app.db import readonly_pool
    async with readonly_pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute('SELECT * FROM bird_financial."account"')


async def test_harness_scores_gold_as_correct_and_garbage_as_wrong(monkeypatch):
    q = harness.load_subset()[0]
    catalog = await load_catalog()
    cfg = {"schema_retrieval": False, "few_shot": False}

    async def echo_gold(system, user):
        return {"text": q["gold_sql_pg"], "input_tokens": 10, "output_tokens": 5, "latency_ms": 1, "cached": False}

    monkeypatch.setattr(harness, "cached_complete", echo_gold)
    sem = asyncio.Semaphore(1)
    rec = await harness.eval_question(q, cfg, {}, catalog, sem)
    assert rec["correct"] and rec["outcome"] == "correct"

    async def wrong(system, user):
        return {"text": "SELECT 1", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1, "cached": False}

    monkeypatch.setattr(harness, "cached_complete", wrong)
    rec = await harness.eval_question(q, cfg, {}, catalog, sem)
    assert rec["outcome"] == "wrong_result" and not rec["correct"]

    async def evil(system, user):
        return {"text": "DROP TABLE x", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1, "cached": False}

    monkeypatch.setattr(harness, "cached_complete", evil)
    rec = await harness.eval_question(q, cfg, {}, catalog, sem)
    assert rec["outcome"] in ("blocked", "exec_error") and not rec["correct"]


def test_summarize_and_cost_none_when_unpriced(monkeypatch):
    monkeypatch.setattr(harness.settings, "llm_model", "some-unpriced-model")
    recs = [
        {"correct": True, "difficulty": "simple", "outcome": "correct", "latency_ms": 10, "input_tokens": 5, "output_tokens": 1},
        {"correct": False, "difficulty": "simple", "outcome": "wrong_result", "latency_ms": 30, "input_tokens": 5, "output_tokens": 1},
    ]
    s = harness.summarize(recs)
    assert s["accuracy"] == 0.5 and s["avg_latency_ms"] == 20 and s["avg_cost_usd"] is None


def test_runs_with_infrastructure_errors_are_not_recordable():
    ok = {"outcomes": {"correct": 5, "wrong_result": 2}}
    broken = {"outcomes": {"correct": 5, "llm_error": 1}}
    assert harness.is_recordable(ok, None)
    assert not harness.is_recordable(broken, None)
    assert not harness.is_recordable(ok, 8)  # smoke run


async def test_f4_harness_path_fixes_bad_first_attempt_and_counts_retries(monkeypatch):
    q = harness.load_subset()[0]
    catalog = await load_catalog()
    cfg = {"schema_retrieval": False, "few_shot": False, "self_correction": True, "max_retries": 2}
    replies = iter(["SELECT no_such_column FROM nowhere", q["gold_sql_pg"]])

    async def scripted(system, user):
        return {"text": next(replies), "input_tokens": 10, "output_tokens": 5, "latency_ms": 100, "cached": False}

    monkeypatch.setattr(harness, "cached_complete", scripted)
    rec = await harness.eval_question(q, cfg, {}, catalog, asyncio.Semaphore(1))
    assert rec["correct"] and rec["retries"] == 1
    assert rec["latency_ms"] == 200 and rec["input_tokens"] == 20  # both calls are accounted for


async def test_f4_harness_path_reports_unfixable_as_exec_error(monkeypatch):
    q = harness.load_subset()[0]
    catalog = await load_catalog()
    cfg = {"schema_retrieval": False, "few_shot": False, "self_correction": True, "max_retries": 1}

    async def always_bad(system, user):
        return {"text": "SELECT nope FROM nowhere", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1, "cached": False}

    monkeypatch.setattr(harness, "cached_complete", always_bad)
    rec = await harness.eval_question(q, cfg, {}, catalog, asyncio.Semaphore(1))
    assert rec["outcome"] == "exec_error" and not rec["correct"] and rec["retries"] == 1
