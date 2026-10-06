"""F8 follow-ups, F9 clarification, F10 feedback loop."""

import httpx
import pytest

from app import baseline, examples, main, pipeline
from app.config import settings
from app.db import admin_pool


def scripted(*replies):
    seen = []

    async def fake(system, user, max_tokens=2048):
        seen.append((system, user))
        return replies[min(len(seen) - 1, len(replies) - 1)]

    fake.seen = seen
    return fake


def sid(name):
    return f"test-{name}-{id(object())}"


# ------------------------------------------------------------------ F8 follow-ups

async def test_followup_prompt_contains_previous_question_and_sql(monkeypatch):
    s = sid("f8")
    llm = scripted("SELECT count(*) AS n FROM data.invoice", "Done.",
                   "SELECT count(*) AS n FROM data.invoice WHERE extract(year FROM invoice_date) = 2024", "Done.")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    first = await pipeline.ask("How many invoices are there?", s)
    assert first.status == "ok"
    second = await pipeline.ask("now only for 2024", s)
    assert second.status == "ok" and second.rows == [[83]]
    prompt = next(u for _, u in llm.seen if "now only for 2024" in u and "Schema:" in u)
    assert "Previous question in this conversation: How many invoices are there?" in prompt
    assert "Previous SQL: SELECT COUNT(*) AS n FROM data.invoice LIMIT 500" in prompt
    assert "follow-up" in prompt


async def test_no_context_for_first_question_or_other_sessions(monkeypatch):
    llm = scripted("SELECT 1 AS one", "ok")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    await pipeline.ask("How many invoices are there?", sid("a"))
    await pipeline.ask("now only for 2024", sid("b"))  # a different session
    gen_prompts = [u for _, u in llm.seen if "Schema:" in u]
    assert all("Previous question" not in u for u in gen_prompts)


async def test_failed_previous_turn_is_not_used_as_context(monkeypatch):
    s = sid("fail")
    llm = scripted("SELECT nope FROM data.invoice")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    assert (await pipeline.ask("broken one", s)).status == "error"
    llm2 = scripted("SELECT 1 AS one", "ok")
    monkeypatch.setattr(pipeline.llm, "complete", llm2)
    await pipeline.ask("next question", s)
    assert all("Previous question" not in u for _, u in llm2.seen)


async def test_previous_turn_is_the_most_recent_answered_one(monkeypatch):
    s = sid("latest")
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT 1 AS one", "ok"))
    await pipeline.ask("question one", s)
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT 2 AS two", "ok"))
    await pipeline.ask("question two", s)
    prev = await pipeline.previous_turn(s)
    assert prev["question"] == "question two" and "2 AS two" in prev["sql"]
    assert await pipeline.previous_turn(None) is None


def test_build_user_prompt_without_previous_is_unchanged():
    assert "Previous" not in baseline.build_user_prompt("q", "SCHEMA")


# ------------------------------------------------------------------ F9 clarification

def test_parse_clarification():
    c = pipeline.parse_clarification("CLARIFY: What does best mean? | By revenue | By orders | By tracks | extra")
    assert c == {"question": "What does best mean?", "options": ["By revenue", "By orders", "By tracks"]}
    assert pipeline.parse_clarification("clarify: Which? | A | B")["options"] == ["A", "B"]
    assert pipeline.parse_clarification("SELECT 1") is None
    assert pipeline.parse_clarification("CLARIFY: only a question") is None
    assert pipeline.parse_clarification("CLARIFY: Which? | just one option") is None


async def test_ambiguous_question_gets_clarification_not_sql(monkeypatch):
    llm = scripted("CLARIFY: What does best mean? | By total revenue | By number of orders")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    r = await pipeline.ask("Who are the best customers?", sid("f9"))
    assert r.status == "clarify" and r.rows == [] and r.sql is None
    assert r.clarification == {"question": "What does best mean?", "options": ["By total revenue", "By number of orders"]}
    assert r.answer == "What does best mean?"
    assert len(llm.seen) == 1  # nothing was executed or summarized
    async with admin_pool.connection() as conn:
        status = (await (await conn.execute("SELECT status FROM app.query_log WHERE id=%s", (r.query_id,))).fetchone())[0]
    assert status == "clarify"


async def test_clarification_rules_are_in_the_product_prompt_only(monkeypatch):
    llm = scripted("SELECT 1 AS one", "ok")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    await pipeline.ask("anything", sid("rules"))
    assert "CLARIFY:" in llm.seen[0][0]
    assert "CLARIFY" not in baseline.system_prompt("bird_x") and "CLARIFY" not in baseline.SYSTEM  # eval prompts untouched


async def test_clarification_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "clarification", False)
    llm = scripted("CLARIFY: Which? | A | B")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    r = await pipeline.ask("ambiguous", sid("off"))
    assert r.status != "clarify" and "CLARIFY" not in llm.seen[0][0]


async def test_only_the_first_attempt_may_ask(monkeypatch):
    calls = []

    async def llm_call(system, user):
        calls.append(user)
        return "SELECT nope FROM data.artist" if len(calls) == 1 else "CLARIFY: Which? | A | B"

    from app.executor import execute_sql

    async def run(sql):
        return await execute_sql(sql, explain_first=True)

    r = await pipeline.correct_loop("s", "u", llm_call, run, max_retries=1, allow_clarify=True)
    assert r.clarification is None and not r.ok  # the retry's "CLARIFY" is treated as (invalid) SQL


async def test_normal_question_is_unaffected_by_clarify_support(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT count(*) AS n FROM data.artist", "275 artists."))
    r = await pipeline.ask("How many artists?", sid("normal"))
    assert r.status == "ok" and r.clarification is None and r.rows == [[275]]


# ------------------------------------------------------------------ F10 feedback loop

@pytest.fixture
def client():
    main._hits.clear()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t")


async def _cleanup(question):
    async with admin_pool.connection() as conn:
        await conn.execute("DELETE FROM app.examples WHERE source='user' AND question=%s", (question,))


async def _count(question):
    async with admin_pool.connection() as conn:
        return (await (await conn.execute(
            "SELECT count(*) FROM app.examples WHERE source='user' AND question=%s AND verified AND embedding IS NOT NULL",
            (question,))).fetchone())[0]


async def test_thumbs_up_saves_a_verified_example_once_and_it_is_retrieved(monkeypatch, client):
    q = "How many artists are there in the catalog zq1?"
    await _cleanup(q)
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT count(*) AS n FROM data.artist", "275."))
    try:
        async with client as c:
            j = (await c.post("/ask", json={"question": q, "session_id": sid("f10")})).json()
            fb = (await c.post("/feedback", json={"query_id": j["query_id"], "rating": 1})).json()
            assert fb == {"ok": True, "saved_example": True}
            again = (await c.post("/feedback", json={"query_id": j["query_id"], "rating": 1})).json()
            assert again["saved_example"] is False  # no duplicate
        assert await _count(q) == 1
        top = (await examples.retrieve_examples(q, k=1))[0]
        assert top["question"] == q and "artist" in top["sql"].lower()  # upvoted pairs show up in later retrievals
    finally:
        await _cleanup(q)


async def test_thumbs_down_and_failed_queries_are_not_saved(monkeypatch, client):
    q = "How many widgets are there zq2?"
    await _cleanup(q)
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT count(*) AS n FROM data.artist", "275."))
    async with client as c:
        ok = (await c.post("/ask", json={"question": q})).json()
        assert (await c.post("/feedback", json={"query_id": ok["query_id"], "rating": -1})).json()["saved_example"] is False
        monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT nope FROM data.artist"))
        bad = (await c.post("/ask", json={"question": q + " bad"})).json()
        assert bad["status"] == "error"
        assert (await c.post("/feedback", json={"query_id": bad["query_id"], "rating": 1})).json()["saved_example"] is False
    assert await _count(q) == 0 and await _count(q + " bad") == 0


async def test_promotion_can_be_disabled(monkeypatch, client):
    q = "How many artists exist zq3?"
    await _cleanup(q)
    monkeypatch.setattr(settings, "feedback_promotes_examples", False)
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT count(*) AS n FROM data.artist", "275."))
    async with client as c:
        j = (await c.post("/ask", json={"question": q})).json()
        assert (await c.post("/feedback", json={"query_id": j["query_id"], "rating": 1})).json()["saved_example"] is False
    assert await _count(q) == 0


async def test_embedding_failure_does_not_lose_feedback(monkeypatch, client):
    q = "How many artists do we have zq4?"
    await _cleanup(q)
    monkeypatch.setattr(pipeline.llm, "complete", scripted("SELECT count(*) AS n FROM data.artist", "275."))

    async def boom(texts, task="RETRIEVAL_DOCUMENT"):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.feedback.embeddings.embed", boom)
    async with client as c:
        j = (await c.post("/ask", json={"question": q})).json()
        fb = (await c.post("/feedback", json={"query_id": j["query_id"], "rating": 1})).json()
    assert fb == {"ok": True, "saved_example": False}
    async with admin_pool.connection() as conn:
        n = (await (await conn.execute("SELECT count(*) FROM app.feedback WHERE query_log_id=%s", (j["query_id"],))).fetchone())[0]
    assert n == 1


async def test_ask_api_returns_clarification_payload(monkeypatch, client):
    monkeypatch.setattr(pipeline.llm, "complete", scripted("CLARIFY: Best how? | By revenue | By orders"))
    async with client as c:
        j = (await c.post("/ask", json={"question": "best customers?"})).json()
    assert j["status"] == "clarify" and j["clarification"]["options"] == ["By revenue", "By orders"]
    assert j["rows"] == [] and j["sql"] is None


async def test_no_clarify_flag_removes_the_rule_and_ignores_clarify_replies(monkeypatch, client):
    llm = scripted("CLARIFY: Best how? | By revenue | By orders")
    monkeypatch.setattr(pipeline.llm, "complete", llm)
    async with client as c:
        j = (await c.post("/ask", json={"question": "best customers? (By revenue)", "no_clarify": True})).json()
    assert j["status"] != "clarify" and j["clarification"] is None  # a user who just chose an option is never asked again
    assert all("CLARIFY" not in system for system, _ in llm.seen)
