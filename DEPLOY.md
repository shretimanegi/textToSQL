# Deploying

Three pieces, all with free tiers: **Postgres + pgvector** (Neon or Supabase), the **API** (Render), the **frontend** (Vercel).
Nothing here is deployed yet; these are the steps and the files that support them.

## 1. Database (Neon or Supabase)
1. Create a project and enable the `vector` extension (Neon: on by default via `CREATE EXTENSION`; Supabase: Database -> Extensions).
2. Use the **direct** (non-pooled) connection string if you have the choice.
3. Initialize it (needs `psql`; on a Mac without it: `brew install libpq`, or run the script inside `docker run --rm -v "$PWD":/repo -w /repo -e ADMIN_URL=... -e READONLY_PASSWORD=... pgvector/pgvector:pg16 bash scripts/init_remote_db.sh`):
   ```
   ADMIN_URL='postgresql://owner:pw@host/db?sslmode=require' READONLY_PASSWORD='pick-a-password' scripts/init_remote_db.sh
   ```
4. Optional, so the Evaluation page shows your ablation numbers: `ADMIN_URL=... scripts/export_eval_runs.sh`
5. You now have two URLs: the owner URL (`ADMIN_DATABASE_URL`) and the same URL with user `readonly_user` + your password (`READONLY_DATABASE_URL`).

## 2. API (Render)
1. New -> Blueprint, point it at this repo (uses `render.yaml`, builds `backend/Dockerfile`).
2. Fill the secrets it asks for: `ADMIN_DATABASE_URL`, `READONLY_DATABASE_URL`, `GEMINI_API_KEY`, `CORS_ORIGINS` (your Vercel URL).
3. `TRUSTED_PROXY_HOPS=1` is already set. Leave it: without it every visitor shares one IP and the 20/hour limit hits everyone together.
4. Check `https://<service>.onrender.com/health` returns `{"ok": true}`.

Free Render services sleep after inactivity, so the first request can take ~30 s. Keep a short demo video as a backup.

## 3. Frontend (Vercel)
1. Import the repo, set **Root Directory** to `frontend`.
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`
3. After the first deploy, put the Vercel URL into the API's `CORS_ORIGINS` and redeploy the API.

## Local
```
docker compose up -d --wait
cd backend && uv run uvicorn app.main:app --port 8010
cd frontend && npm run dev -- --port 3010
```
(`LLM_PROVIDER=mock` runs the API without an LLM key, with canned answers, for UI testing.)
