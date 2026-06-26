-- V9: Append-only grants for support_guardrail_rejections (Story 5.5 code review).
--
-- Mirrors V5__append_only_grants.sql: the guardrail rejection audit log is
-- append-only (no modified_at column, no V2 UPDATE trigger). sboai_app may
-- SELECT/INSERT only — UPDATE/DELETE are revoked so a compromised credential
-- cannot rewrite or erase the audit trail.
--
-- Idempotent / re-runnable: GRANT and REVOKE are naturally idempotent, and the
-- statements are wrapped in a single DO block guarded by role existence (V2
-- idempotency lesson) so a missing sboai_app role skips cleanly instead of
-- aborting the migration.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sboai_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON support_guardrail_rejections TO sboai_app';
        EXECUTE 'REVOKE UPDATE, DELETE ON support_guardrail_rejections FROM sboai_app';
    ELSE
        RAISE NOTICE 'sboai_app role missing — append-only grants skipped (run 02_roles.sh first)';
    END IF;
END
$$;
