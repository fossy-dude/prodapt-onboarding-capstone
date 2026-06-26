-- V3: Subscriber registration extensions (Story 1.6).
--
-- Story 1.6 Dev Notes say "no new migration" on the assumption that V1 had every
-- column the ACs need. That did not hold for two fields, so this migration adds
-- exactly the minimum required (per user decision 2026-06-20):
--
--   1. identity_registrations.registration_id — human-readable Registration ID
--      (AC #2: REG-{YYYYMMDD}-{8 hex}); persisted on the registration record.
--      Registration *status* ('REGISTRATION_COMPLETE') lives on the existing
--      identity_registrations.status VARCHAR column — the subscriber_status_enum
--      is NOT extended (master record keeps its default).
--
--   2. ops_order_fulfilment.plan_id → NULLable — a registration-time fulfilment
--      order legitimately has no plan yet (the plan is chosen at recharge,
--      Story 1.10). AC #6 only requires the order row to exist with state CREATED.
--
-- PII encryption: NOT applied at the column level (user decision 2026-06-20 —
-- encryption is an application-layer concern for consumption/sharing, not the DB
-- column). No BYTEA PII columns are added here.
--
-- Idempotent patterns (IF NOT EXISTS / SET NOT NULL after backfill) so the
-- migration is safe to re-run after a Flyway repair.

-- ============================================================
-- 1. Registration ID + status width on identity_registrations
-- ============================================================

-- 'REGISTRATION_COMPLETE' (21 chars) exceeds the original VARCHAR(20); widen so the
-- AC #1 status value fits (per user decision 2026-06-20: status lives here, not on
-- the subscriber enum).
ALTER TABLE identity_registrations ALTER COLUMN status TYPE VARCHAR(30);

ALTER TABLE identity_registrations ADD COLUMN IF NOT EXISTS registration_id VARCHAR(30);

-- Backfill any pre-existing rows (none on a fresh baseline) so NOT NULL is safe.
UPDATE identity_registrations
SET registration_id = 'REG-' || to_char(submitted_at, 'YYYYMMDD') || '-' || substr(md5(id::text), 1, 8)
WHERE registration_id IS NULL;

ALTER TABLE identity_registrations ALTER COLUMN registration_id SET NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_identity_registrations_registration_id') THEN
        ALTER TABLE identity_registrations
            ADD CONSTRAINT uq_identity_registrations_registration_id UNIQUE (registration_id);
    END IF;
END $$;

-- ============================================================
-- 2. ops_order_fulfilment.plan_id → NULLable
-- ============================================================

ALTER TABLE ops_order_fulfilment ALTER COLUMN plan_id DROP NOT NULL;
