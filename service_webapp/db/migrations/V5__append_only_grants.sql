-- V5: Append-only grants for the three immutable billing tables (Story 2.4, AC #2 / FR-59 / NFR-4).
--
-- V1/V2 already mark billing_audit_log, billing_cdr_events, billing_transactions as
-- append-only (no modified_at column, no V2 UPDATE trigger). What was MISSING is
-- grant enforcement: the app role (sboai_app) must PHYSICALLY be unable to UPDATE or
-- DELETE, so immutability is enforced at the DB layer (not by code convention). This
-- migration grants only INSERT + SELECT and revokes UPDATE + DELETE from sboai_app on
-- all three append-only tables. Without it, "append-only" is convention only.
--
-- Roles exist from Story 1.2 (docker/postgres/init/02_roles.sh): sboai_app (RW app
-- connection), sboai_flyway (runs migrations, CREATEROLE). This migration runs as
-- sboai_flyway; the REVOKE targets sboai_app. Extensions already exist
-- (01_extensions.sql) — migrations must NOT CREATE EXTENSION.
--
-- Version resolution: V4 was already taken by V4__profile_address_columns.sql
-- (Story 1.9, profile address PII). The Story 2.4 spec assumed only V1/V2/V3 existed
-- and said to coordinate: "Whichever lands first takes V4." V4 landed first (unrelated
-- to append-only grants), so this append-only-grants migration is V5. See Story 2.4
-- Completion Notes.
--
-- Idempotent / re-runnable: GRANT and REVOKE are naturally idempotent, and every
-- statement is wrapped in a single DO block guarded by role existence (V2 idempotency
-- lesson) so a missing sboai_app role skips cleanly instead of aborting the migration.

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'sboai_app') THEN
        -- Append-only privilege set: SELECT + INSERT only (FR-59).
        EXECUTE 'GRANT SELECT, INSERT ON billing_audit_log    TO sboai_app';
        EXECUTE 'GRANT SELECT, INSERT ON billing_cdr_events   TO sboai_app';
        EXECUTE 'GRANT SELECT, INSERT ON billing_transactions TO sboai_app';

        -- Revoke mutation so sboai_app cannot rewrite history (NFR-4 / TRAI 6-yr).
        EXECUTE 'REVOKE UPDATE, DELETE ON billing_audit_log    FROM sboai_app';
        EXECUTE 'REVOKE UPDATE, DELETE ON billing_cdr_events   FROM sboai_app';
        EXECUTE 'REVOKE UPDATE, DELETE ON billing_transactions FROM sboai_app';
    ELSE
        RAISE NOTICE 'sboai_app role missing — append-only grants skipped (run 02_roles.sh first)';
    END IF;
END
$$;
