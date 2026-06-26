-- V4: Profile address columns (Story 1.9).
--
-- identity_subscribers has NO address columns today: the registration flow
-- (Story 1.6) only fed the address into the one-way TRAI CAF SHA-256 audit hash,
-- never persisting it as queryable PII (V3 migration comment, user decision
-- 2026-06-20). Story 1.9 AC #1 ("saved address" displayed) and AC #3 ("edits
-- their address") need queryable address PII, so add NULLable structured address
-- columns mirroring the registration form shape. Existing subscribers keep NULL
-- until they edit their profile (no backfill needed).
--
-- PII encryption: NOT applied at the column level (user decision 2026-06-20 —
-- encryption is an application-layer concern for consumption/sharing, not the DB
-- column). These columns store plaintext, consistent with subscriber_name/email.
--
-- Idempotent (IF NOT EXISTS) so the migration is safe to re-run after a Flyway repair.

ALTER TABLE identity_subscribers ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(200);
ALTER TABLE identity_subscribers ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(200);
ALTER TABLE identity_subscribers ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE identity_subscribers ADD COLUMN IF NOT EXISTS state VARCHAR(100);
ALTER TABLE identity_subscribers ADD COLUMN IF NOT EXISTS pin_code VARCHAR(10);
