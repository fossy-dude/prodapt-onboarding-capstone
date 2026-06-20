-- Runs as postgres superuser, connected to the sboai database (already created by POSTGRES_DB env var).
-- Grants schema-level permissions to application roles so Flyway can run DDL
-- and the app role can use all objects created by Flyway.
-- Allow Flyway to create objects in the public schema
GRANT CREATE ON SCHEMA public TO sboai_flyway;
GRANT USAGE ON SCHEMA public TO sboai_flyway;
-- Allow app user to use all objects in the public schema
GRANT USAGE ON SCHEMA public TO sboai_app;
GRANT USAGE ON SCHEMA public TO sboai_readonly;
-- Default privileges: objects created by sboai_flyway are automatically accessible
-- by sboai_app (DML) and sboai_readonly (SELECT). Required because Flyway runs as
-- sboai_flyway, not postgres, so newly created tables would otherwise be inaccessible.
ALTER DEFAULT PRIVILEGES FOR ROLE sboai_flyway IN SCHEMA public
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLES TO sboai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sboai_flyway IN SCHEMA public
GRANT USAGE,
    SELECT ON SEQUENCES TO sboai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sboai_flyway IN SCHEMA public
GRANT SELECT ON TABLES TO sboai_readonly;
-- LangFuse gets its own database; auto-migrated by LangFuse on startup via LANGFUSE_AUTO_MIGRATE
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (
        SELECT
        FROM pg_database
        WHERE datname = 'langfuse'
    ) \gexec
GRANT ALL PRIVILEGES ON DATABASE langfuse TO langfuse_app;