#!/usr/bin/env bash
# Copy the local ablation results (app.eval_runs) to the hosted database so the /eval page shows them.
#   ADMIN_URL='postgresql://owner:pw@host/db?sslmode=require' scripts/export_eval_runs.sh
set -euo pipefail
: "${ADMIN_URL:?set ADMIN_URL to the hosted owner connection string}"
cd "$(dirname "$0")/.."
docker compose exec -T db pg_dump -U postgres -d texttosql --data-only --column-inserts -t app.eval_runs \
  | psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q
echo "eval_runs copied"
