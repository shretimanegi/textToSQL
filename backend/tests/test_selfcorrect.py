"""F4: error/empty result -> LLM fixes, at most 2 retries."""

import pytest

from app import pipeline
from app.executor import execute_sql
from app.safety import UnsafeSQL


def scripted(*sqls):
    calls = []

    async def llm_call(system, user):
        calls.append(user)
        return sqls[min(len(calls) - 1, len(sqls) - 1)]

    llm_call.calls = calls
    return llm_call


async def run(sql):
    return await execute_sql(sql, explain_first=True)


async def loop(llm_call, max_retries=2):
    return await pipeline.correct_loop("sys", "USER PROMPT", llm_call, run, max_retries=max_retries)


async def test_good_first_try_no_retries():
    llm_call = scripted("SELECT count(*) AS n FROM data.artist")
    r = await loop(llm_call)
    assert r.ok and r.retries == 0 and r.result.rows == [[275]] and len(llm_call.calls) == 1


async def test_sql_error_is_fixed_on_retry_and_error_is_sent_back():
    llm_call = scripted("SELECT nope FROM data.artist", "SELECT count(*) AS n FROM data.artist")
    r = await loop(llm_call)
    assert r.ok and r.retries == 1 and r.result.rows == [[275]]
    fix = llm_call.calls[1]
    assert "USER PROMPT" in fix and "SELECT nope FROM data.artist" in fix and 'column "nope" does not exist' in fix


async def test_two_failures_then_success_uses_both_retries():
    llm_call = scripted("SELECT nope FROM data.artist", "SELECT x FROM data.nothing", "SELECT 1 AS one")
    r = await loop(llm_call)
    assert r.ok and r.retries == 2 and len(llm_call.calls) == 3


async def test_gives_up_after_max_retries():
    llm_call = scripted("SELECT nope FROM data.artist")
    r = await loop(llm_call)
    assert not r.ok and r.retries == 2 and len(llm_call.calls) == 3 and "nope" in r.error and not r.blocked


async def test_max_retries_zero_means_single_attempt():
    llm_call = scripted("SELECT nope FROM data.artist", "SELECT 1")
    r = await loop(llm_call, max_retries=0)
    assert not r.ok and len(llm_call.calls) == 1


async def test_empty_result_triggers_retry_with_filter_hint():
    llm_call = scripted("SELECT * FROM data.customer WHERE country = 'brazil'",
                        "SELECT count(*) AS n FROM data.customer WHERE country = 'Brazil'")
    r = await loop(llm_call)
    assert r.ok and r.retries == 1 and r.result.rows == [[5]]
    assert "0 rows" in llm_call.calls[1] and "filters" in llm_call.calls[1]


async def test_still_empty_after_retries_is_returned_as_valid_empty_result():
    llm_call = scripted("SELECT * FROM data.customer WHERE country = 'Atlantis'")
    r = await loop(llm_call)
    assert r.ok and r.result.rows == [] and r.retries == 2 and len(llm_call.calls) == 3


async def test_unsafe_sql_is_fed_back_and_can_be_repaired():
    llm_call = scripted("SELECT 1; DROP TABLE data.album", "SELECT 1 AS one")
    r = await loop(llm_call)
    assert r.ok and r.retries == 1 and "safety checker" in llm_call.calls[1]


async def test_persistently_unsafe_sql_ends_blocked_and_never_runs():
    llm_call = scripted("DROP TABLE data.album")
    r = await loop(llm_call)
    assert not r.ok and r.blocked
    async def count():
        return (await execute_sql("SELECT count(*) FROM data.album")).rows[0][0]
    assert await count() == 347


async def test_explain_catches_errors_before_executing():
    with pytest.raises(Exception, match="does not exist"):
        await execute_sql("SELECT nope FROM data.artist", explain_first=True)


async def test_normalizer_is_applied_before_running():
    seen = []

    async def run_sql(sql):
        seen.append(sql)
        return await execute_sql("SELECT 1 AS one")

    r = await pipeline.correct_loop("s", "u", scripted("select  x"), run_sql, normalize=lambda s: "NORMALIZED")
    assert seen == ["NORMALIZED"] and r.ok


def test_thinking_config_per_model_family(monkeypatch):
    from app import llm
    from app.config import settings
    monkeypatch.setattr(settings, "llm_thinking_level", "")
    monkeypatch.setattr(settings, "llm_thinking_budget", 0)
    assert llm.thinking_config() == {"thinkingBudget": 0}  # Gemini 2.5 / 3.1 flash-lite
    monkeypatch.setattr(settings, "llm_thinking_level", "minimal")
    assert llm.thinking_config() == {"thinkingLevel": "minimal"}  # Gemini 3.5: budget is rejected
    monkeypatch.setattr(settings, "llm_thinking_level", "")
    monkeypatch.setattr(settings, "llm_thinking_budget", -1)
    assert llm.thinking_config() is None
