#!/usr/bin/env bash
# One-time setup of a hosted Postgres (Neon / Supabase) with pgvector.
#   ADMIN_URL='postgresql://owner:pw@host/db?sslmode=require' READONLY_PASSWORD='choose-one' scripts/init_remote_db.sh
# Creates the data + app schemas, loads Chinook, and creates readonly_user (SELECT on data only, 5 s timeout).
set -euo pipefail
: "${ADMIN_URL:?set ADMIN_URL to the owner connection string}"
: "${READONLY_PASSWORD:?set READONLY_PASSWORD}"
cd "$(dirname "$0")/.."
for f in db/init/01_roles_schemas.sql db/init/02_app_tables.sql db/init/03_chinook.sql; do
  echo "applying $f"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -f "$f"
done
echo "creating readonly_user"
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -v ro_pw="$READONLY_PASSWORD" <<'SQL'
CREATE ROLE readonly_user LOGIN PASSWORD :'ro_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA data TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO readonly_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO readonly_user;
ALTER ROLE readonly_user SET statement_timeout = '5s';
ALTER ROLE readonly_user SET default_transaction_read_only = on;
ALTER ROLE readonly_user SET search_path = data;
SQL
echo "done. Build READONLY_DATABASE_URL with user readonly_user and your READONLY_PASSWORD."
