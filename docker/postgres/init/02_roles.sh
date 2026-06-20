#!/bin/bash
# Runs as postgres superuser at container creation.
# Shell script required to expand ${POSTGRES_*_PASSWORD} env vars into SQL.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Application user: owns schema, runs all DML
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sboai_app') THEN
            CREATE USER sboai_app WITH PASSWORD '${POSTGRES_APP_PASSWORD}';
        END IF;
    END
    \$\$;

    -- Read-only reporting user: ML/analytics queries, never on write path
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sboai_readonly') THEN
            CREATE USER sboai_readonly WITH PASSWORD '${POSTGRES_READONLY_PASSWORD}';
        END IF;
    END
    \$\$;

    -- Flyway migration user: runs DDL; CREATEROLE accepted for local dev (ARCH-13.4a Callout 3)
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sboai_flyway') THEN
            CREATE USER sboai_flyway WITH PASSWORD '${POSTGRES_FLYWAY_PASSWORD}' CREATEROLE;
        END IF;
    END
    \$\$;

    GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO sboai_app;
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO sboai_readonly;
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO sboai_flyway;
EOSQL
