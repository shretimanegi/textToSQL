# Progress

## Phase 1: Foundation, F1, F5 — DONE (2026-10-06)

- Docker Compose: `pgvector/pgvector:pg16`; init scripts in `db/init/` (extension, schemas, `app` tables + HNSW indexes, Chinook in `data`, `readonly_user` grants).
- Chinook: 11 tables in `data` (from lerocha/chinook-database v1.4.5, `CREATE DATABASE` lines stripped).
- F5 safety, four layers:
  1. `readonly_user`: SELECT on `data` only, no `app` access, `statement_timeout=5s`, `default_transaction_read_only=on`.
  2. `app/safety.py`: sqlglot, single SELECT only; blocks DML/DDL/COPY/SET/locks/SELECT INTO, `pg_*`/`lo_*`/dblink/etc. functions, non-`data` schemas, system relations.
  3. LIMIT 500 injected or capped, `SET LOCAL statement_timeout`.
  4. `app/executor.py`: `BEGIN READ ONLY ... ROLLBACK`.
- F1 baseline (`app/baseline.py`): full introspected schema (cols, PKs, FKs) in prompt, Gemini via `app/llm.py` (provider switch: gemini/anthropic/openai). Logs every ask to `app.query_log`.
- API: `POST /ask`, `POST /run-sql`, `GET /schema` (others come in later phases).
- Tests: 158 pass (`cd backend && uv run pytest`), including 3 live-LLM Chinook questions against Gemini (skipped automatically if no key is set). Red-team: 54 malicious SQL cases blocked at the parser and the executor, 5 "obedient LLM" questions blocked end to end, plus DB-level tests that bypass the parser (role cannot write or read `app`, 5s timeout, read-only txn).

### Run it
```
cp .env.example .env        # then set passwords and GEMINI_API_KEY
docker compose up -d --wait
cd backend && uv sync && uv run pytest
uv run uvicorn app.main:app --port 8010
```

### Decisions
- LLM: Gemini behind `LLM_PROVIDER`, called over REST; now `gemini-3.1-flash-lite` because `gemini-2.5-flash` allows only 20 free requests/day on this key (quota is per model); Claude/OpenAI paths remain but are untested; embeddings dim 1536 per SPEC (OpenAI); revisit when starting F2.
- Tooling: uv, psycopg 3 (async pool).
- Host ports: Postgres on **5436** (5432/5433/5435 taken by other local containers), API dev port 8010 (8000 taken).
- `/ask` `answer` is a placeholder ("Returned N rows."); the real one-line summary and `chart_spec` land with F6.
- `version()`, `current_setting`, `nextval` etc. are blocked as extra hardening.

### Not yet verified
- F1 accuracy beyond 3 simple questions; the real baseline number comes from the Phase 2 eval harness.
- Gemini free-tier rate limits may matter for the 200-question eval runs.

## Phase 2 (retrieval + eval) — IN PROGRESS (started 2026-10-06)

### Done: F7 eval harness + F1 baseline recorded
- BIRD dev (1,534 q, 11 DBs) migrated to Postgres, one `bird_<db_id>` schema each (`backend/eval/migrate_bird.py`). Row counts match SQLite for every table. Original mixed-case names kept (quoted).
- Separate DB role `eval_readonly` (SELECT on `bird_*` only, no `data`/`app`), so `readonly_user` stays limited to `data`. Safety layer and executor now take a `schema` argument chosen by server code.
- Gold SQL translated SQLite -> Postgres with sqlglot (`eval/gold.py`): **1,410 of 1,534 run** (92%). The other 124 fail on dialect gaps (SQLite loose typing, `julianday`, stricter GROUP BY) and are excluded from the pool.
- Fixed subset: 200 questions, seed 42, stratified by difficulty (125 simple / 58 moderate / 17 challenging), `backend/eval/subset.json`.
- Metric: BIRD EX (set equality of row tuples; ordered comparison if gold has a top-level ORDER BY). Unordered comparison ignores duplicate rows, like BIRD.
- Run: `cd backend && uv run python -m eval.run_eval --config f1` (LLM responses cached in `backend/eval/cache/`, so reruns are free and interrupted runs resume). Results land in `app.eval_runs` plus `backend/eval/results/*.json`.

### Ablation table (200 BIRD dev questions, gemini-3.1-flash-lite, evidence hint on, no thinking)
| Configuration | Execution accuracy | Avg latency | Avg cost/question |
| --- | --- | --- | --- |
| F1 baseline (full schema) | **67.0%** (134/200) | 14.5 s* | n/a (free tier) |
| + F2 schema retrieval | | | |
| + F3 few-shot retrieval | | | |
| + F4 self-correction | | | |

F1 by difficulty: simple 69.6%, moderate 62.1%, challenging 64.7% (n=17, noisy). Outcomes: 134 correct, 61 wrong result, 3 execution errors (all SQLite `strftime`), 2 blocked by the safety layer (two statements joined by `;`).
*Latency is inflated by free-tier rate limiting at concurrency 4; treat it as relative only.

### Decisions / caveats
- Predicted SQL goes through the same catalog-based identifier normalization as gold (case-insensitive resolution, then quoting), reproducing SQLite's rules. Without it, unquoted `T1.CDSCode` failed on Postgres and the baseline measured quoting discipline. Recorded as `identifier_normalization` in each run's config.
- Eval executes with an unrestricted row cap and 30 s timeout (product stays LIMIT 500 / 5 s) so large gold results are not truncated.
- BIRD declares FKs on non-unique columns that Postgres cannot enforce; all 105 FKs are kept in `backend/eval/data/bird_fks.json` and used in the schema prompt.
- 67% is higher than published BIRD baselines. Likely contributors: newer model, evidence hint, set-based metric, and the pool excludes the 8% of questions whose gold SQL is SQLite-specific. Compare configurations against each other, not to the leaderboard.
- Gemini free tier: `gemini-2.5-flash` hit its 20/day cap; `gemini-3.1-flash-lite` completed 200 questions. All ablation rows must use the same model. Daily cap on 3.1-flash-lite is unknown (>245 requests so far).

### F2 + F3 built; evaluation of both PENDING the LLM daily quota (2026-10-06)
- **Embeddings are now local** (`fastembed`, `BAAI/bge-small-en-v1.5`, 384 dims): no API quota, works offline. `schema_docs` and `examples` are `vector(384)`; `app/db_setup.py` upgrades existing volumes (and `db/init/02` matches for fresh ones). Gemini embeddings remain available via `EMBEDDING_PROVIDER=gemini` but need vector(1536) columns. Reason: `gemini-embedding-001` allows only 1,000 requests/day, which indexing plus one eval run exhausts.
- **F2** (`app/index_schema.py`, `app/retrieval.py`): LLM-written description + 3 sample values per column (one LLM call per table, cached), embedded locally; 862 columns across Chinook and 11 BIRD DBs. Query = question + hint, top-15 columns, expanded to full tables plus bridge tables (FK-adjacent to >= 2 hit tables), PKs/FKs between included tables only. Table recall 90.0% over the 200 questions; prompt holds 4.9 of 7.2 tables on average (input tokens about -60%).
- **F3** (`app/seed_examples.py`, `app/examples.py`): 9,428 BIRD *train* pairs seeded into `app.examples` (SQLite translated to Postgres, identifiers quoted; train DBs are disjoint from dev and zero train questions equal a dev question, both tested). Top-3 most similar verified pairs per question go into the prompt, labelled as cross-database style examples. Only `train.json` was fetched (range request into the 8.9 GB zip), not the databases.
- **Neither run is recorded.** `gemini-3.1-flash-lite` allows 500 LLM requests/day and the day's quota ran out: F2 completed 107/200, F3 0/200. The harness refuses to record runs with `llm_error`, so `app.eval_runs` still holds only F1. Partial F2 preview (107 completed questions, skewed towards 4 databases, NOT comparable): F1 66/107 (61.7%) vs F2 62/107 (57.9%), F2 fixes 1, breaks 5.
- **To finish:** after the quota resets (about 8 h after 16:05 UTC), run `uv run python -m eval.run_eval --config f2` then `--config f3`. Cached responses mean about 293 new LLM calls in total, within one day's 500.
- Superseded: the earlier Gemini-embedding F2 preview (64.6% on 130) was computed with a different retrieval backbone and is discarded.

## Phase 3 (product) — BUILT, not deployed (2026-10-06)
Started before the F2/F3 ablation rows existed, at the user's explicit request (this overrides the SPEC gate).

- **F4 self-correction** (`app/pipeline.py: correct_loop`): runs `EXPLAIN` first, and on a DB error, a safety rejection, or a 0-row result sends question + failed SQL + error back to the LLM, at most 2 retries. A 0-row answer that cannot be improved is returned as a valid empty result. Tested with a scripted LLM (13 cases). Eval config `f4` (= F3 + retries) reuses F3's cached first attempts, so it only pays for retries. **Its accuracy / "95% execute without error" is NOT measured yet** (needs LLM quota).
- **Product pipeline** (`/ask`): schema retrieval and few-shot are OFF by default for the 11-table Chinook DB (`PRODUCT_SCHEMA_RETRIEVAL`, `PRODUCT_FEW_SHOT`); self-correction is ON. Flip the flags once the ablation says retrieval helps.
- **API** now has everything in SPEC: `/ask` (answer, sql, rows, columns, `chart_spec`, retries, query_id), `/run-sql`, `/feedback`, `/schema` (with descriptions), `/examples`, `/eval/runs`, `/health`. 20 questions/IP/hour rate limit, CORS allow-list. `chart_spec` is chosen on the backend (time -> line, one category + one measure -> bar, ID-like numbers and >50 categories -> none).
- **F6 UI** (`frontend/`, Next.js 16 + Tailwind + Recharts): sidebar with clickable examples and searchable schema, thread of result cards (one-line answer, paginated table capped at 500, auto chart, collapsible editable SQL with Run, thumbs up/down, `retries: N` badge, failure and blocked states), top bar (dataset picker, link to `/eval`), and an Evaluation page that shows measured configs and "Not run yet" for the rest. Charts follow the dataviz rules (single blue series, 4 px rounded bar ends, 2 px lines, hairline grid, tooltips, no legend for one series). Dark mode follows the OS.
- **Tests:** backend 244 pass / 3 skipped (live LLM); frontend 20 pass (`cd frontend && npm test`); production build and lint clean; `npm audit --omit=dev` found 0 vulnerabilities.
- **Verified by hand in a browser** with `LLM_PROVIDER=mock` (canned answers, for UI testing only): bar chart, line chart, failure state, blocked state, edit-and-Run, Evaluation page.
- **Deploy artifacts, ready but NOT deployed:** `backend/Dockerfile` (image built and smoke-tested against the local DB), `render.yaml`, `scripts/init_remote_db.sh` (verified on a throwaway Postgres: schemas, Chinook, readonly role isolation), `scripts/export_eval_runs.sh`, `DEPLOY.md`. Deploying needs your Neon/Supabase, Render and Vercel accounts, so I have not done it.
- **Security fixes found while building:** the rate limiter trusted the first `X-Forwarded-For` entry, which a client can forge; it now uses the entry the trusted proxy appended (`TRUSTED_PROXY_HOPS`, 0 locally, 1 on Render), with tests. psycopg prepared statements are disabled so pooled hosted Postgres works.
- **Known quirks:** typing into the input before the page finishes hydrating (dev server, right after a reload) can be lost; not seen in the production build but not tested there. Mobile layout and dark mode are implemented but not visually checked.

### Not verified
- A real `/ask` with a live LLM through the UI (quota exhausted today); everything except the LLM call is covered.
- F2, F3, F4 accuracy numbers (pending the scheduled rerun).
- Any deployed environment.

### Next
1. Rerun evals after the quota resets: `uv run python -m eval.run_eval --config f2`, then `f3`, then `f4`. Fill the ablation table, decide the product retrieval flags from the numbers.
2. Deploy per DEPLOY.md (needs your accounts).
3. Phase 4 is built (below); what remains there is live-LLM verification.

## Phase 4 (extras) — BUILT, not verified against a live LLM (2026-10-06)
Started before the F2-F4 numbers existed, at the user's request ("continue and do this later"). Everything below is tested with scripted LLMs; none of the prompt-dependent behaviour has been seen with a real model yet.

- **F8 follow-ups:** `/ask` looks up the session's most recent *successful* turn in `app.query_log` and puts its question + SQL in the prompt, with an instruction to rewrite that SQL only if the new question is a follow-up ("now only for 2024"), otherwise ignore it. Other sessions and failed turns never leak in. The input shows a follow-up hint after the first answer.
- **F9 clarification:** the product prompt lets the model reply `CLARIFY: question | option | option [| option]` instead of SQL. Only the first attempt may ask (fix retries must produce SQL). The card shows the question with clickable options, and choosing one re-asks with `no_clarify: true`, so the user is never asked twice (this loop was found and fixed in browser testing). Eval prompts are untouched (tested). `CLARIFICATION=false` turns it off.
- **F10 feedback loop:** a thumbs-up on a query that ran fine (`status='ok'`) saves (question, final SQL) to `app.examples` as `source='user'`, `verified=TRUE`, embedded locally; never duplicated, never for failed queries or thumbs-down, and an embedding failure does not lose the rating. Retrieval picks it up (tested). `FEEDBACK_PROMOTES_EXAMPLES=false` turns it off. The UI says "saved as an example" only when that actually happened.
- **Tests:** backend 261 pass / 3 skipped; frontend 23 pass.
- **Browser-verified** with the mock LLM: clarification card, option click, answer, thumbs-up confirmation. The mock-created example was deleted afterwards; `app.examples` holds 9,428 seed rows and 0 user rows.

### Risks and open points
- **Example poisoning:** on a public demo anyone can thumbs-up a query and it becomes a "verified" few-shot example whose question text is injected into other users' prompts. Mitigated only by: SQL must have passed the safety layer and run, no duplicates. Not mitigated: a malicious *question text*. Before going public, either leave `PRODUCT_FEW_SHOT` off (the default, so saved examples are not used yet), review examples before they count, or add a per-IP feedback limit.
- **F10 only matters if `PRODUCT_FEW_SHOT=true`.** Decide from the F3 vs F2 numbers.
- **Over/under-asking is a prompt question.** Whether the real model asks for clarification only on truly ambiguous questions (and never on the sample questions) is untested; the spec's 50 hand-written questions (10 ambiguous, 10 follow-up) are the right check once LLM quota is available. Same for whether follow-up rewriting works on a real model.
- **Embedding model on the hosted API:** F10 loads the local embedding model (about 130 MB download on first use). On a small free Render instance this may be slow or run out of memory; if so, set `FEEDBACK_PROMOTES_EXAMPLES=false` there.
- Input handling: the submit handler now reads the input's live value; earlier "typed text lost after Enter" sightings were not conclusively explained (not reproduced after the change).

### Next
1. After the quota resets (scheduled rerun does F2, F3, F4): set the product flags from the numbers.
2. Build the 50-question product eval (10 ambiguous, 10 follow-up) and run it live.
3. Deploy per DEPLOY.md (needs your accounts).

### Update 2026-10-07 07:45 IST: scheduled F2/F3/F4 rerun failed on quota again
- A one-call probe of `gemini-3.1-flash-lite` succeeded at 07:42, but all three runs then failed immediately: F2 had the same 93 uncached questions error out, F3 and F4 all 200. **Zero new LLM calls succeeded** (no new cache entries). The API reported `GenerateRequestsPerDayPerProjectPerModel` (500 free requests/day) exhausted, retry in about 21.7 h (about 05:30 IST on Oct 8, which looks like a 00:00 UTC reset).
- Nothing was recorded: the harness refused the runs (it never records runs containing `llm_error`), and `app.eval_runs` still holds only F1 (67.0%). The ablation table above is unchanged.
- Unexplained: the daily quota was already used up in a window that should have reset at 05:30 IST, and my runs made no successful calls. Either the reset time is not what I assumed or something else is using this key. Check usage at https://ai.dev/rate-limit before the next attempt. A passing single-call probe is **not** proof of headroom.
- The next attempt is scheduled for 06:03 IST on Oct 8; the faster fix is enabling billing on the key.

### Update 2026-10-07 (later): ablation re-run on gemini-3.5-flash-lite — mostly done, F1/F2/F3 each a few questions short
Why a new model: `gemini-3.1-flash-lite`'s free daily quota (500) was exhausted and a second and third API key from other accounts were rejected with 403 "project denied access". Quota is per model, so the whole ablation is being redone on `gemini-3.5-flash-lite` (same 500/day cap, `thinkingLevel: minimal`, the 3.x equivalent of "no thinking"; it rejects `thinkingBudget: 0`). A different model means **F1 must be re-measured too**: gains across models are meaningless, so the old F1 (67.0% on 3.1-flash-lite) is kept only as a separate data point and the Evaluation page now shows a model per row and refuses to compute a gain across models. The cache key only includes the thinking level when set, so the old model's cached answers stay valid.

State at the daily cap (nothing in `app.eval_runs` is partial; the harness refuses runs with API errors):
| Run (3.5-flash-lite) | Finished | Correct | Status |
| --- | --- | --- | --- |
| F1 | 134/200 | 85 | incomplete, 66 questions hit the cap, **not recorded** |
| F2 | 196/200 | 121 | incomplete (4 rate-limit errors), **not recorded** |
| F3 | 197/200 | 115 | incomplete (3 rate-limit errors), **not recorded** |
| F4 | 200/200 | **120 (60.0%)** | complete, recorded (id 3) |

**Partial paired preview, not a result:** on the 131 questions that finished in all four configs, F1 62.6% (82), F2 60.3% (79), F3 55.7% (73), F4 57.3% (75). Paired flips: F1->F2 fixes 3 / breaks 6; F2->F3 fixes 6 / breaks 12; F3->F4 fixes 2 / breaks 0. So on this model **schema retrieval and few-shot retrieval did not help (they cost accuracy), and self-correction helped slightly**. The differences are small (131 questions, single-digit flips) and could be noise; the full 200 will say more. F2 table recall 90%; prompt tokens F2 824 / F3 1,198 / F4 1,291 (F1 not finished). F4: every query executed (0 execution errors, so the 95% target is met; F3 was already at 98.5%), 9 questions needed a retry and 2 of those ended correct.
Hypothesis for F3 hurting (untested): the 3 examples come from other databases, so they add noise and pull the model toward SQLite-style SQL and unrelated table names. Worth testing with same-domain examples, not just BIRD train.

Scheduled for 06:08 IST on 2026-10-08 (session-only): finish F1, F2, F3 on this model (about 73 calls) and fill the table. Defaults stay `PRODUCT_SCHEMA_RETRIEVAL=false`, `PRODUCT_FEW_SHOT=false`, which this data supports.

### Update 2026-10-07 (evening): all four rows recorded, but on three models (user's decision)
The user asked to stop re-running and use whichever models still had quota for F2 and F3 (keeping F1 and F4 as they were). Candidates tested with the real request: `gemini-3-flash-preview` has a 20 requests/day cap (died after 16 calls); `gemma-4-26b-a4b-it` worked (fast, accepts `thinkingLevel: minimal`), `gemma-4-31b-it` too slow, 3.8-flash/flash-latest reject minimal thinking. F2 and F3 were run on `gemma-4-26b-a4b-it` (so at least F2 vs F3 is a same-model comparison).

| Config | Model | Accuracy | Notes |
| --- | --- | --- | --- |
| F1 | gemini-3.1-flash-lite | 67.0% (134/200) | simple 69.6 / moderate 62.1 / challenging 64.7 |
| F2 | gemma-4-26b-a4b-it | 62.0% (124/200) | 837 prompt tokens, table recall 90%, 94.0% execute |
| F3 | gemma-4-26b-a4b-it | 61.0% (122/200) | 1,211 prompt tokens, 93.5% execute |
| F4 | gemini-3.5-flash-lite | 60.0% (120/200) | 100% execute, 4.5% retry rate |

- **Only F2 -> F3 is a valid step:** -1.0 pt, fixes 13 / breaks 15 (noise). F1 -> F2 and F3 -> F4 cross models and mean nothing; the Evaluation page shows the model per row and no longer computes a gain across models. The earlier partial same-model data on 3.5-flash-lite (131 questions) said the same: retrieval/few-shot did not help, self-correction helped slightly.
- **Spec targets:** "+10 points over baseline" NOT met; "95%+ execute without error" met by F4 (200/200). No evidence yet that retrieval or few-shot are worth enabling; defaults stay off.
- Superseded: the scheduled 06:08 IST rerun on 3.5-flash-lite was cancelled (it would have re-recorded F1/F2/F3 against this decision). The old incomplete 3.5-flash-lite F1/F2/F3 results (66/4/3 questions short) are unrecorded.
- Environment note: the laptop slept for hours during background runs, which froze them and caused network-error failures; keep it awake for long runs.
- To get a clean, valid table: pick ONE model with enough quota (enable billing, or ~2 days on a 500/day lite model) and run all four configs on it. `.env` was never changed from `gemini-3.1-flash-lite`.
