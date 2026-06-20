#!/bin/bash
set -e

# Grant langfuse_app all privileges on the langfuse database and public schema
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname="langfuse" <<-EOSQL
  GRANT ALL ON SCHEMA public TO langfuse_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO langfuse_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO langfuse_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO langfuse_app;
EOSQL

echo "LangFuse permissions configured"
