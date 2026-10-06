"""The /ask pipeline: prompt -> SQL -> (EXPLAIN +) execute -> self-correct (F4) -> chart + answer."""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import psycopg

from app import baseline, examples, llm, retrieval
from app.charts import chart_spec
from app.config import settings
from app.db import admin_pool
from app.executor import QueryResult, execute_sql
from app.safety import UnsafeSQL

LLMCall = Callable[[str, str], Awaitable[str]]
RunSQL = Callable[[str], Awaitable[QueryResult]]
Normalize = Callable[[str], str]


@dataclass
class Attempt:
    sql: str
    error: str | None = None  # None = ran fine
    n_rows: int | None = None


_CLARIFY = re.compile(r"^\s*CLARIFY:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def parse_clarification(text: str) -> dict | None:
    """'CLARIFY: question | opt1 | opt2 [| opt3]' -> {question, options}, or None if absent/malformed."""
    m = _CLARIFY.search(text)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|") if p.strip()]
    if len(parts) < 3:  # a question and at least two options
        return None
    return {"question": parts[0], "options": parts[1:4]}


@dataclass
class LoopResult:
    ok: bool
    sql: str | None
    result: QueryResult | None
    retries: int
    attempts: list[Attempt] = field(default_factory=list)
    blocked: bool = False  # the final failure was the safety layer, not the database
    error: str | None = None
    clarification: dict | None = None  # F9: the model asked instead of answering


def _fix_prompt(user: str, attempt: Attempt, blocked: bool) -> str:
    if attempt.error is None:
        problem = ("The query ran but returned 0 rows. Check the filters (spelling, case, value formats, "
                   "join conditions) against the schema and the sample values, and write a corrected query.")
    elif blocked:
        problem = (f"The query was rejected by the safety checker: {attempt.error}. "
                   "Write exactly one read-only SELECT statement.")
    else:
        problem = f"PostgreSQL returned this error: {attempt.error}\nFix the query."
    return f"{user}\n\nYour previous attempt:\n{attempt.sql}\n\n{problem}\nOutput only the corrected SQL."


async def correct_loop(
    system: str, user: str, llm_call: LLMCall, run_sql: RunSQL,
    max_retries: int = 2, normalize: Normalize | None = None, allow_clarify: bool = False,
) -> LoopResult:
    """Generate SQL, run it, and on a database error or an empty result ask the LLM to fix it (F4).

    Up to `max_retries` fixes. A 0-row answer that cannot be improved is returned as-is (a valid result).
    """
    prompt = user
    attempts: list[Attempt] = []
    best_empty: tuple[str, QueryResult] | None = None
    last_blocked, last_error = False, None
    for i in range(max_retries + 1):
        text = await llm_call(system, prompt)
        if allow_clarify and i == 0:  # only the first attempt may ask; fixes must produce SQL
            clarification = parse_clarification(text)
            if clarification:
                return LoopResult(False, None, None, retries=0, clarification=clarification)
        sql = baseline.extract_sql(text)
        if normalize:
            try:
                sql = normalize(sql)
            except Exception:
                pass  # unparseable: let the database/safety layer produce the error
        try:
            qr = await run_sql(sql)
        except UnsafeSQL as e:
            attempt, last_blocked, last_error = Attempt(sql, str(e)), True, str(e)
        except psycopg.Error as e:
            msg = str(e).strip().splitlines()[0]
            attempt, last_blocked, last_error = Attempt(sql, msg), False, msg
        else:
            attempts.append(Attempt(qr.sql, None, len(qr.rows)))
            if qr.rows:
                return LoopResult(True, qr.sql, qr, retries=i, attempts=attempts)
            best_empty = best_empty or (qr.sql, qr)
            attempt, last_blocked, last_error = Attempt(qr.sql, None, 0), False, None
            if i == max_retries:
                break
            prompt = _fix_prompt(user, attempt, False)
            continue
        attempts.append(attempt)
        if i == max_retries:
            break
        prompt = _fix_prompt(user, attempt, last_blocked)
    if best_empty:
        return LoopResult(True, best_empty[0], best_empty[1], retries=max_retries, attempts=attempts)
    return LoopResult(False, attempts[-1].sql, None, retries=max_retries, attempts=attempts,
                      blocked=last_blocked, error=last_error)


# ---------------------------------------------------------------- product /ask

@dataclass
class AskResult:
    status: str  # ok | blocked | error
    question: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    answer: str = ""
    error: str | None = None
    retries: int = 0
    query_id: int | None = None
    chart: dict = field(default_factory=lambda: {"type": "none"})
    clarification: dict | None = None


_schema_cache: dict | None = None


async def previous_turn(session_id: str | None) -> dict | None:
    """F8: the last answered question of this session, if any."""
    if not session_id:
        return None
    async with admin_pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT question, final_sql FROM app.query_log WHERE session_id = %s AND status = 'ok'"
            " AND final_sql IS NOT NULL ORDER BY id DESC LIMIT 1", (session_id,))).fetchone()
    return {"question": row[0], "sql": row[1]} if row else None


async def _product_prompt(question: str, previous: dict | None = None, allow_clarify: bool = True) -> tuple[str, str]:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = await baseline.get_schema("data")
    only = None
    if settings.product_schema_retrieval:
        only = (await retrieval.retrieve("chinook", "data", question)).tables
    shots = ""
    if settings.product_few_shot:
        shots = examples.render_examples(await examples.retrieve_examples(question))
    schema_text = baseline.render_schema(_schema_cache, "data", only)
    return baseline.product_system(allow_clarify), baseline.build_user_prompt(question, schema_text, None, shots, previous)


async def summarize(question: str, qr: QueryResult) -> str:
    """One plain-English sentence. Falls back to a template if the LLM is unavailable."""
    n = len(qr.rows)
    fallback = "No rows matched your question." if n == 0 else f"Found {n} row{'s' if n != 1 else ''}."
    if n == 0:
        return fallback
    sample = "\n".join(" | ".join(str(v) for v in r) for r in qr.rows[:8])
    try:
        text = await llm.complete(
            "You write one-sentence answers for non-technical users from a query result. "
            "Be concrete, use the actual numbers, no jargon, no mention of SQL. One sentence only.",
            f"Question: {question}\nColumns: {', '.join(qr.columns)}\nRows ({n} total, first {min(n, 8)}):\n{sample}\n\nAnswer:",
            max_tokens=120)
        text = re.sub(r"\s+", " ", text).strip()
        return text or fallback
    except Exception:
        return fallback


async def _log(session_id: str | None, r: AskResult, generated: str | None, latency_ms: int) -> int:
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO app.query_log (session_id, question, generated_sql, final_sql, retries, status, latency_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (session_id, r.question, generated, r.sql if r.status == "ok" else None, r.retries, r.status, latency_ms))
        return (await cur.fetchone())[0]


async def ask(question: str, session_id: str | None = None, allow_clarify: bool = True) -> AskResult:
    start = time.monotonic()
    result = AskResult(status="error", question=question)
    first_sql: str | None = None
    try:
        allow_clarify = allow_clarify and settings.clarification
        system, user = await _product_prompt(question, await previous_turn(session_id), allow_clarify)

        async def llm_call(s: str, u: str) -> str:
            return await llm.complete(s, u)

        async def run(sql: str) -> QueryResult:
            return await execute_sql(sql, explain_first=True)

        loop = await correct_loop(system, user, llm_call, run,
                                  max_retries=settings.max_retries if settings.self_correction else 0,
                                  allow_clarify=allow_clarify)
        first_sql = loop.attempts[0].sql if loop.attempts else None
        result.retries, result.sql = loop.retries, loop.sql
        if loop.clarification:
            result.status, result.clarification = "clarify", loop.clarification
            result.answer = loop.clarification["question"]
        elif loop.ok:
            qr = loop.result
            result.status, result.columns, result.rows = "ok", qr.columns, qr.rows
            result.chart = chart_spec(qr.columns, qr.rows)
            result.answer = await summarize(question, qr)
        else:
            result.status = "blocked" if loop.blocked else "error"
            result.error = loop.error
            result.answer = ("That query was blocked by the safety layer." if loop.blocked
                             else "I couldn't build a working query.")
    except Exception as e:  # LLM/API failures, DB down
        result.error = f"{type(e).__name__}: {e}"
        result.answer = "I couldn't build a working query."
    result.query_id = await _log(session_id, result, first_sql, int((time.monotonic() - start) * 1000))
    return result
