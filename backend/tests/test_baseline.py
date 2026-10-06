import pytest
import httpx

from app import baseline, pipeline
from app.main import app


def test_extract_sql_plain():
    assert baseline.extract_sql("SELECT 1") == "SELECT 1"


def test_extract_sql_fenced():
    assert baseline.extract_sql("Here:\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"


async def test_schema_text_lists_all_tables_and_keys():
    text = await baseline.get_schema_text()
    for t in ["album", "artist", "customer", "employee", "genre", "invoice",
              "invoice_line", "media_type", "playlist", "playlist_track", "track"]:
        assert f"TABLE data.{t} (" in text
    assert "PRIMARY KEY" in text and "FOREIGN KEY" in text
    assert "app." not in text


def _mock_llm(monkeypatch, sql):
    seen = {}

    async def fake(system, user, max_tokens=1024):
        seen.setdefault("system", system)  # first call = SQL generation; later ones are summaries
        seen.setdefault("user", user)
        return sql

    monkeypatch.setattr(pipeline.llm, "complete", fake)
    return seen


async def test_ask_happy_path_logs_and_prompts_full_schema(monkeypatch):
    seen = _mock_llm(monkeypatch, "```sql\nSELECT count(*) AS n FROM data.artist\n```")
    r = await pipeline.ask("How many artists are there?", session_id="s1")
    assert r.status == "ok" and r.rows == [[275]] and r.columns == ["n"]
    assert "TABLE data.track" in seen["user"] and "TABLE data.invoice_line" in seen["user"]
    from app.db import admin_pool
    async with admin_pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT status, final_sql FROM app.query_log WHERE id=%s", (r.query_id,))).fetchone()
    assert row[0] == "ok" and "LIMIT 500" in row[1]


async def test_ask_sql_error_is_reported_not_raised(monkeypatch):
    _mock_llm(monkeypatch, "SELECT nope FROM data.album")
    r = await pipeline.ask("bad column")
    assert r.status == "error" and "nope" in r.error


async def test_ask_llm_failure_is_reported(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline.llm, "complete", boom)
    r = await pipeline.ask("anything")
    assert r.status == "error" and "api down" in r.error


async def test_api_endpoints(monkeypatch):
    _mock_llm(monkeypatch, "SELECT name FROM data.genre ORDER BY genre_id LIMIT 3")
    # No lifespan: the session fixture in conftest already opened the pools.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/ask", json={"question": "genres?", "session_id": "t"})
        assert r.status_code == 200 and r.json()["status"] == "ok" and len(r.json()["rows"]) == 3

        r = await c.post("/run-sql", json={"sql": "SELECT 1 AS x"})
        assert r.status_code == 200 and r.json()["rows"] == [[1]]

        assert (await c.post("/run-sql", json={"sql": "DROP TABLE data.album"})).status_code == 400
        assert (await c.post("/run-sql", json={"sql": "SELECT * FROM app.query_log"})).status_code == 400

        s = (await c.get("/schema")).json()
        assert len(s["tables"]) == 11


from app.config import settings

_has_key = bool({"gemini": settings.gemini_api_key, "anthropic": settings.anthropic_api_key,
                 "openai": settings.openai_api_key}.get(settings.llm_provider))


@pytest.mark.skipif(not _has_key, reason="no LLM API key in .env")
@pytest.mark.parametrize("question,expected", [
    ("How many artists are there?", 275),
    ("How many tracks are in the database?", 3503),
    ("How many customers are from Brazil?", 5),
])
async def test_live_simple_chinook_questions(question, expected):
    r = await pipeline.ask(question)
    if r.error and "quota" in r.error:
        pytest.skip("LLM free-tier daily quota exhausted")
    assert r.status == "ok", r.error
    assert r.rows[0][0] == expected
