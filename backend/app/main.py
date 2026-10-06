import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import feedback as feedback_store
from app import pipeline
from app.config import settings
from app.db import admin_pool, close_pools, open_pools
from app.executor import execute_sql
from app.safety import UnsafeSQL
from app.sample_questions import SAMPLES


@asynccontextmanager
async def lifespan(_: FastAPI):
    await open_pools()
    yield
    await close_pools()


app = FastAPI(title="Text-to-SQL Assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

# ---- rate limit: N /ask calls per client IP per hour, in memory (one process, good enough for a demo)
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """Each trusted proxy appends the address it saw, so the real client is `hops` entries from the END.
    Entries before that are client-supplied and forgeable, so they are never used."""
    hops = settings.trusted_proxy_hops
    fwd = request.headers.get("x-forwarded-for")
    if hops > 0 and fwd:
        ips = [p.strip() for p in fwd.split(",") if p.strip()]
        if len(ips) >= hops:
            return ips[-hops]
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= settings.rate_limit_per_hour:
        retry = int(3600 - (now - q[0])) + 1
        raise HTTPException(429, f"Rate limit reached ({settings.rate_limit_per_hour} questions per hour). Try again in {retry // 60 + 1} min.",
                            headers={"Retry-After": str(retry)})
    q.append(now)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = Field(default=None, max_length=100)
    no_clarify: bool = False  # set when the user just picked a clarification option


class RunSqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)


class FeedbackRequest(BaseModel):
    query_id: int
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/ask")
async def ask(req: AskRequest, request: Request):
    check_rate_limit(client_ip(request))
    r = await pipeline.ask(req.question.strip(), req.session_id, allow_clarify=not req.no_clarify)
    return jsonable_encoder({
        "status": r.status, "answer": r.answer, "sql": r.sql,
        "columns": r.columns, "rows": r.rows, "chart_spec": r.chart,
        "retries": r.retries, "query_id": r.query_id, "error": r.error, "clarification": r.clarification,
    })


@app.post("/run-sql")
async def run_sql(req: RunSqlRequest):
    try:
        qr = await execute_sql(req.sql)
    except UnsafeSQL as e:
        raise HTTPException(400, f"blocked: {e}")
    except psycopg.Error as e:
        raise HTTPException(400, str(e).strip().splitlines()[0])
    from app.charts import chart_spec
    return jsonable_encoder({"sql": qr.sql, "columns": qr.columns, "rows": qr.rows,
                             "chart_spec": chart_spec(qr.columns, qr.rows)})


@app.post("/feedback")
async def feedback(req: FeedbackRequest):
    async with admin_pool.connection() as conn:
        exists = await (await conn.execute("SELECT 1 FROM app.query_log WHERE id = %s", (req.query_id,))).fetchone()
        if not exists:
            raise HTTPException(404, "unknown query_id")
        await conn.execute("INSERT INTO app.feedback (query_log_id, rating, comment) VALUES (%s, %s, %s)",
                           (req.query_id, req.rating, req.comment))
    saved = False
    if req.rating == 1 and settings.feedback_promotes_examples:
        saved = await feedback_store.promote_to_example(req.query_id)
    return {"ok": True, "saved_example": saved}


@app.get("/schema")
async def schema():
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT c.table_name, c.column_name, c.data_type, d.description"
            " FROM information_schema.columns c"
            " LEFT JOIN app.schema_docs d ON d.db_id = 'chinook' AND d.table_name = c.table_name AND d.column_name = c.column_name"
            " WHERE c.table_schema = 'data' ORDER BY c.table_name, c.ordinal_position")
        rows = await cur.fetchall()
    tables: dict[str, list[dict]] = defaultdict(list)
    for t, c, d, desc in rows:
        tables[t].append({"name": c, "type": d, "description": desc})
    return {"dataset": "Chinook (music store)", "tables": [{"name": t, "columns": cols} for t, cols in tables.items()]}


@app.get("/examples")
async def examples():
    return {"examples": [q for q, _ in SAMPLES]}


@app.get("/eval/runs")
async def eval_runs():
    async with admin_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, config, dataset, accuracy, n_questions, created_at FROM app.eval_runs ORDER BY id")
        rows = await cur.fetchall()
    runs = []
    for i, cfg, dataset, acc, n, created in rows:
        s = cfg.get("summary", {})
        runs.append({
            "id": i, "key": cfg.get("key"), "name": cfg.get("name"), "model": cfg.get("model"),
            "dataset": dataset, "accuracy": acc, "n_questions": n, "created_at": created,
            "by_difficulty": s.get("by_difficulty"), "avg_latency_ms": s.get("avg_latency_ms"),
            "avg_input_tokens": s.get("avg_input_tokens"), "avg_cost_usd": s.get("avg_cost_usd"),
            "retrieval": s.get("retrieval"), "outcomes": s.get("outcomes"),
        })
    return jsonable_encoder({"runs": runs})
