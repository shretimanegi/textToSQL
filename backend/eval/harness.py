"""Run one ablation config over the fixed subset and score execution accuracy."""

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import sqlglot
from sqlglot import exp
from psycopg.types.json import Jsonb

from app import baseline, embeddings, examples, pipeline, retrieval
from app.config import settings
from app.db import admin_pool
from app.executor import execute_sql
from app.safety import UnsafeSQL
from eval import configs
from eval.cache import CACHE_DIR, cached_complete
from eval.compare import gold_is_ordered, results_match
from eval.gold import GOLD_STATUS, NO_CAP, load_catalog, normalize, load_questions
from eval.make_subset import SUBSET
from eval.migrate_bird import schema_name

RESULTS_DIR = Path(__file__).parent / "results"


def load_subset() -> list[dict]:
    ids = set(json.loads(SUBSET.read_text())["question_ids"])
    gold = {r["question_id"]: r for r in json.loads(GOLD_STATUS.read_text())}
    out = []
    for q in load_questions():
        if q["question_id"] in ids:
            out.append({**q, "gold_sql_pg": gold[q["question_id"]]["sql_pg"]})
    return out


def is_recordable(summary: dict, limit: int | None) -> bool:
    """Only complete, full-subset runs enter the ablation table. Infrastructure failures (quota, API
    errors) are not model mistakes; rerun to resume from the cache instead of recording them."""
    return limit is None and summary["outcomes"].get("llm_error", 0) == 0


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """None when the model has no price entry (free tier / unknown), never a misleading 0."""
    if settings.llm_model not in configs.PRICE_PER_M:
        return None
    pin, pout = configs.PRICE_PER_M[settings.llm_model]
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


def gold_tables(gold_sql: str) -> set[str]:
    tree = sqlglot.parse_one(gold_sql, read="postgres")
    ctes = {c.alias.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name.lower() not in ctes}


async def build_prompt(q: dict, cfg: dict, schema_cache: dict) -> tuple[str, str, dict]:
    """(system, user, meta) for this question under this config. F3 hooks in here."""
    schema = schema_name(q["db_id"])
    if schema not in schema_cache:
        schema_cache[schema] = await baseline.get_schema(schema)
    structure = schema_cache[schema]
    evidence = q["evidence"] if configs.EVIDENCE else None
    meta: dict = {}
    only = None
    if cfg["schema_retrieval"]:
        query_text = q["question"] + (f"\n{evidence}" if evidence else "")
        r = await retrieval.retrieve(q["db_id"], schema, query_text)
        only = r.tables
        needed = gold_tables(q["gold_sql_pg"])
        meta = {"retrieved_tables": sorted(only), "n_tables_total": len(structure),
                "gold_tables_covered": needed <= {t.lower() for t in only}}
    schema_text = baseline.render_schema(structure, schema, only)
    shots = ""
    if cfg["few_shot"]:
        exs = await examples.retrieve_examples(q["question"])
        shots = examples.render_examples(exs)
        meta["example_ids"] = [e["id"] for e in exs]
    return baseline.system_prompt(schema), baseline.build_user_prompt(q["question"], schema_text, evidence, shots), meta


async def eval_question(q: dict, cfg: dict, schema_cache: dict, catalog: dict, sem: asyncio.Semaphore) -> dict:
    schema = schema_name(q["db_id"])
    rec = {"question_id": q["question_id"], "db_id": q["db_id"], "difficulty": q["difficulty"],
           "question": q["question"], "gold_sql": q["gold_sql_pg"], "pred_sql": None,
           "correct": False, "outcome": None, "error": None,
           "latency_ms": 0, "input_tokens": 0, "output_tokens": 0}
    async with sem:
        try:
            system, user, meta = await build_prompt(q, cfg, schema_cache)
            rec.update(meta)
            gold = await execute_sql(q["gold_sql_pg"], schema=schema, max_rows=NO_CAP, timeout_s=configs.EXEC_TIMEOUT_S)
            norm = lambda sql: normalize(sql, catalog[q["db_id"]], read="postgres")  # SQLite-style identifiers

            async def run_sql(sql: str):
                return await execute_sql(sql, schema=schema, max_rows=NO_CAP, timeout_s=configs.EXEC_TIMEOUT_S)

            if cfg.get("self_correction"):
                async def llm_call(s: str, u: str) -> str:
                    resp = await cached_complete(s, u)
                    rec["latency_ms"] += resp["latency_ms"]
                    rec["input_tokens"] += resp["input_tokens"]
                    rec["output_tokens"] += resp["output_tokens"]
                    return resp["text"]

                loop = await pipeline.correct_loop(system, user, llm_call, run_sql,
                                                   max_retries=cfg.get("max_retries", 2), normalize=norm)
                rec["retries"] = loop.retries
                rec["pred_sql"] = loop.sql
                if not loop.ok:
                    rec.update(outcome="blocked" if loop.blocked else "exec_error", error=loop.error)
                    return rec
                pred = loop.result
            else:
                resp = await cached_complete(system, user)
                rec.update(latency_ms=resp["latency_ms"], input_tokens=resp["input_tokens"],
                           output_tokens=resp["output_tokens"])
                if not resp["text"].strip():
                    rec.update(outcome="llm_error", error="empty completion")
                    return rec
                rec["pred_sql"] = baseline.extract_sql(resp["text"])
                try:
                    rec["pred_sql"] = norm(rec["pred_sql"])
                except Exception:
                    pass
                pred = await run_sql(rec["pred_sql"])
            rec["correct"] = results_match(pred.rows, gold.rows, ordered=gold_is_ordered(q["gold_sql_pg"]))
            rec["outcome"] = "correct" if rec["correct"] else "wrong_result"
        except UnsafeSQL as e:
            rec.update(outcome="blocked", error=str(e))
        except psycopg.Error as e:
            rec.update(outcome="exec_error", error=str(e).splitlines()[0][:300])
        except Exception as e:  # LLM/API failure
            rec.update(outcome="llm_error", error=f"{type(e).__name__}: {str(e)[:300]}")
    return rec


def summarize(records: list[dict]) -> dict:
    n = len(records)
    by_diff = defaultdict(lambda: [0, 0])
    outcomes = defaultdict(int)
    for r in records:
        by_diff[r["difficulty"]][0] += r["correct"]
        by_diff[r["difficulty"]][1] += 1
        outcomes[r["outcome"]] += 1
    with_ret = [r for r in records if "gold_tables_covered" in r]
    retrieval_stats = None
    if with_ret:
        retrieval_stats = {
            "table_recall": sum(r["gold_tables_covered"] for r in with_ret) / len(with_ret),
            "avg_tables_in_prompt": sum(len(r["retrieved_tables"]) for r in with_ret) / len(with_ret),
            "avg_tables_available": sum(r["n_tables_total"] for r in with_ret) / len(with_ret),
        }
    inp = sum(r["input_tokens"] for r in records)
    out = sum(r["output_tokens"] for r in records)
    return {
        "n_questions": n,
        "accuracy": sum(r["correct"] for r in records) / n if n else 0.0,
        "by_difficulty": {d: {"correct": c, "n": t, "accuracy": c / t} for d, (c, t) in by_diff.items()},
        "outcomes": dict(outcomes),
        "retry_rate": sum(1 for r in records if r.get("retries")) / n if n else 0.0,
        "executes_without_error": sum(1 for r in records if r["outcome"] in ("correct", "wrong_result")) / n if n else 0.0,
        "retrieval": retrieval_stats,
        "avg_latency_ms": sum(r["latency_ms"] for r in records) / n if n else 0.0,
        "avg_input_tokens": inp / n if n else 0.0,
        "avg_output_tokens": out / n if n else 0.0,
        "avg_cost_usd": (estimate_cost(inp, out) / n if n else 0.0) if estimate_cost(inp, out) is not None else None,
    }


async def run(config_key: str, limit: int | None = None, concurrency: int = 4, record: bool = True) -> dict:
    cfg = configs.CONFIGS[config_key]
    embeddings.CACHE_DIR = CACHE_DIR
    questions = load_subset()[:limit]
    schema_cache: dict = {}
    catalog = await load_catalog()
    sem = asyncio.Semaphore(concurrency)
    t0 = time.monotonic()
    records = await asyncio.gather(*(eval_question(q, cfg, schema_cache, catalog, sem) for q in questions))
    summary = summarize(records)
    summary["wall_seconds"] = round(time.monotonic() - t0, 1)

    run_config = {"key": config_key, **cfg, "provider": settings.llm_provider, "model": settings.llm_model,
                  "thinking_budget": settings.llm_thinking_budget, "thinking_level": settings.llm_thinking_level, "evidence": configs.EVIDENCE, "identifier_normalization": True,
                  "exec_timeout_s": configs.EXEC_TIMEOUT_S, "subset_limit": limit,
                  "metric": "BIRD EX (set equality; ordered if gold has ORDER BY)", "summary": summary}
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{config_key}_{stamp}.json"
    path.write_text(json.dumps({"config": run_config, "records": records}, indent=1, default=str))
    run_config["incomplete"] = summary["outcomes"].get("llm_error", 0) > 0
    path.write_text(json.dumps({"config": run_config, "records": records}, indent=1, default=str))
    if record and is_recordable(summary, limit):
        async with admin_pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.eval_runs (config, dataset, accuracy, n_questions) VALUES (%s, %s, %s, %s)",
                (Jsonb(run_config), configs.DATASET, summary["accuracy"], summary["n_questions"]))
    return {"summary": summary, "path": str(path)}
