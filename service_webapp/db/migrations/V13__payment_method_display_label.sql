-- Add display_label column to recharge_payment_methods.
-- The account API stores a human-readable masked label (e.g. "•••• 4242" or "user@upi"),
-- which is distinct from the existing last_four VARCHAR(4) used by receipts/USSD flows.
-- Rows created by other paths (USSD, integration test fixtures) that omit this column
-- get an empty string rather than NULL so the frontend string type contract is upheld.
ALTER TABLE recharge_payment_methods
    ADD COLUMN display_label VARCHAR(100) NOT NULL DEFAULT '';
