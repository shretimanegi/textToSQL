import httpx
import pytest

from app import main, pipeline
from app.config import settings
from app.db import admin_pool
from app.executor import execute_sql
from app.sample_questions import SAMPLES


@pytest.fixture
def client():
    main._hits.clear()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t")


def mock_llm(monkeypatch, *replies):
    n = {"i": 0}

    async def fake(system, user, max_tokens=2048):
        n["i"] += 1
        return replies[min(n["i"] - 1, len(replies) - 1)]

    monkeypatch.setattr(pipeline.llm, "complete", fake)


@pytest.mark.parametrize("question,sql", SAMPLES, ids=[q[:30] for q in SAMPLES and [s[0] for s in SAMPLES]])
async def test_every_sample_question_is_answerable(question, sql):
    r = await execute_sql(sql)
    assert r.rows, question


async def test_ask_returns_all_card_parts_with_chart(monkeypatch, client):
    mock_llm(monkeypatch, "SELECT country, count(*) AS customers FROM data.customer GROUP BY country ORDER BY customers DESC LIMIT 5",
             "The USA has the most customers.")
    async with client as c:
        j = (await c.post("/ask", json={"question": "customers per country?", "session_id": "s"})).json()
    assert j["status"] == "ok" and j["answer"] == "The USA has the most customers."
    assert j["columns"] == ["country", "customers"] and len(j["rows"]) == 5 and j["retries"] == 0
    assert j["chart_spec"] == {"type": "bar", "x": "country", "y": "customers"} and j["query_id"]
    assert "LIMIT" in j["sql"]


async def test_ask_self_corrects_and_reports_retries(monkeypatch, client):
    mock_llm(monkeypatch, "SELECT nope FROM data.artist", "SELECT count(*) AS n FROM data.artist", "There are 275 artists.")
    async with client as c:
        j = (await c.post("/ask", json={"question": "how many artists"})).json()
    assert j["status"] == "ok" and j["retries"] == 1 and j["rows"] == [[275]]


async def test_ask_failure_message(monkeypatch, client):
    mock_llm(monkeypatch, "SELECT nope FROM data.artist")
    async with client as c:
        j = (await c.post("/ask", json={"question": "x"})).json()
    assert j["status"] == "error" and j["answer"] == "I couldn't build a working query."
    assert j["sql"] == "SELECT nope FROM data.artist" and j["retries"] == 2 and "nope" in j["error"]


async def test_ask_blocked_malicious_sql(monkeypatch, client):
    mock_llm(monkeypatch, "DROP TABLE data.album")
    async with client as c:
        j = (await c.post("/ask", json={"question": "drop the album table"})).json()
        assert j["status"] == "blocked" and j["rows"] == []
        assert (await c.post("/run-sql", json={"sql": "SELECT count(*) AS n FROM data.album"})).json()["rows"] == [[347]]


async def test_ask_validation(client):
    async with client as c:
        assert (await c.post("/ask", json={"question": ""})).status_code == 422
        assert (await c.post("/ask", json={"question": "x" * 501})).status_code == 422


async def test_rate_limit_per_ip(monkeypatch, client):
    monkeypatch.setattr(settings, "rate_limit_per_hour", 3)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    mock_llm(monkeypatch, "SELECT 1 AS one", "ok")
    async with client as c:
        codes = [(await c.post("/ask", json={"question": "q"}, headers={"x-forwarded-for": "1.2.3.4"})).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        other = await c.post("/ask", json={"question": "q"}, headers={"x-forwarded-for": "5.6.7.8"})
        assert other.status_code == 200
        blocked = await c.post("/ask", json={"question": "q"}, headers={"x-forwarded-for": "1.2.3.4"})
        assert "Retry-After" in blocked.headers


def test_rate_limit_window_expires(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_hour", 1)
    main._hits.clear()
    main.check_rate_limit("z", now=0.0)
    with pytest.raises(Exception):
        main.check_rate_limit("z", now=10.0)
    main.check_rate_limit("z", now=3601.0)


async def test_run_sql_returns_chart_and_blocks_unsafe(client):
    async with client as c:
        ok = (await c.post("/run-sql", json={"sql": "SELECT name, genre_id FROM data.genre LIMIT 3"})).json()
        assert ok["columns"] == ["name", "genre_id"] and len(ok["rows"]) == 3
        assert (await c.post("/run-sql", json={"sql": "DELETE FROM data.album"})).status_code == 400
        assert (await c.post("/run-sql", json={"sql": "SELECT * FROM app.query_log"})).status_code == 400
        assert (await c.post("/run-sql", json={"sql": "SELECT nope FROM data.album"})).status_code == 400


async def test_feedback_roundtrip_and_validation(monkeypatch, client):
    mock_llm(monkeypatch, "SELECT 1 AS one", "One.")
    async with client as c:
        qid = (await c.post("/ask", json={"question": "fb"})).json()["query_id"]
        assert (await c.post("/feedback", json={"query_id": qid, "rating": 1, "comment": "nice"})).json() == {"ok": True, "saved_example": True}
        assert (await c.post("/feedback", json={"query_id": qid, "rating": 5})).status_code == 422
        assert (await c.post("/feedback", json={"query_id": 99999999, "rating": 1})).status_code == 404
    async with admin_pool.connection() as conn:
        row = await (await conn.execute("SELECT rating, comment FROM app.feedback WHERE query_log_id=%s", (qid,))).fetchone()
    assert row == (1, "nice")
    async with admin_pool.connection() as conn:  # the upvote also promoted this pair to a few-shot example
        await conn.execute("DELETE FROM app.examples WHERE source='user' AND question='fb'")


async def test_schema_examples_eval_runs_health(client):
    async with client as c:
        s = (await c.get("/schema")).json()
        assert len(s["tables"]) == 11
        track = next(t for t in s["tables"] if t["name"] == "track")
        assert any(col["description"] for col in track["columns"])
        ex = (await c.get("/examples")).json()["examples"]
        assert len(ex) >= 6 and all(isinstance(q, str) for q in ex)
        runs = (await c.get("/eval/runs")).json()["runs"]
        assert any(r["key"] == "f1" and abs(r["accuracy"] - 0.67) < 1e-9 for r in runs)
        assert (await c.get("/health")).json() == {"ok": True}


async def test_cors_header_for_allowed_origin(client):
    async with client as c:
        r = await c.get("/health", headers={"origin": "http://localhost:3010"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3010"
        r = await c.get("/health", headers={"origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers


def _req(headers, host="9.9.9.9"):
    from starlette.requests import Request
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()], "client": (host, 1)}
    return Request(scope)


def test_client_ip_ignores_forwarded_header_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert main.client_ip(_req({"x-forwarded-for": "1.1.1.1"})) == "9.9.9.9"


def test_client_ip_cannot_be_spoofed_behind_one_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    # the attacker prepends fake addresses; the proxy appends the address it really saw
    assert main.client_ip(_req({"x-forwarded-for": "6.6.6.6, 7.7.7.7, 203.0.113.5"})) == "203.0.113.5"
    assert main.client_ip(_req({})) == "9.9.9.9"


async def test_rate_limit_cannot_be_bypassed_by_forging_forwarded_for(monkeypatch, client):
    monkeypatch.setattr(settings, "rate_limit_per_hour", 2)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    mock_llm(monkeypatch, "SELECT 1 AS one", "ok")
    async with client as c:
        codes = [(await c.post("/ask", json={"question": "q"}, headers={"x-forwarded-for": f"{i}.{i}.{i}.{i}, 203.0.113.5"})).status_code
                 for i in range(1, 5)]
    assert codes == [200, 200, 429, 429]
