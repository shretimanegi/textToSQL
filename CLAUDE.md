# Text-to-SQL Assistant

Read SPEC.md before any task. It is the source of truth for features, data model, safety rules and API.

## Build order (follow strictly; don't start a phase until the previous one works)
1. Foundation: Docker Compose with Postgres 16 + pgvector, Chinook loaded into the `data` schema, `app` schema tables from SPEC.md. Then F1 baseline generation and F5 safety layer with red-team tests.
2. Retrieval + eval: F7 eval harness (200 BIRD dev questions), record baseline. Then F2 schema retrieval and F3 few-shot retrieval, measuring each.
3. Product: F4 self-correction, F6 result card UI (Next.js), deploy.
4. Extras: F8 follow-ups, F9 clarification, F10 feedback loop, eval dashboard.

## Rules
- Backend: Python + FastAPI. Frontend: Next.js + Tailwind + Recharts.
- Generated SQL must always go through the safety layer: read-only role, sqlglot SELECT-only check, 5s timeout, LIMIT 500.
- Never commit API keys; use a .env file and keep .env.example updated.
- Write tests for every feature, and run them before saying a task is done.
- Keep a short PROGRESS.md: what's done, what's next, any decisions made.