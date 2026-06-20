-- Runs as postgres superuser, connected to the sboai database (already created by POSTGRES_DB env var).
-- Grants schema-level permissions to application roles so Flyway can run DDL
-- and the app role can use all objects created by Flyway.

-- Allow Flyway to create objects in the public schema
GRANT CREATE ON SCHEMA public TO sboai_flyway;
GRANT USAGE ON SCHEMA public TO sboai_flyway;

-- Allow app user to use all objects in the public schema
GRANT USAGE ON SCHEMA public TO sboai_app;
GRANT USAGE ON SCHEMA public TO sboai_readonly;

-- LangFuse gets its own database; auto-migrated by LangFuse on startup
CREATE DATABASE langfuse;
GRANT ALL PRIVILEGES ON DATABASE langfuse TO postgres;
