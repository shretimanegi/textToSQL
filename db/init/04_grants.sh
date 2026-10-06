#!/bin/bash
# Runs as the superuser at first init. Password comes from the container env.
set -euo pipefail
psql -v ON_ERROR_STOP=1 -v ro_pw="$READONLY_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
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
