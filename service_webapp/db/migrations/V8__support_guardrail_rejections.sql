-- V8: support_guardrail_rejections table (Story 5.5)
-- Append-only audit log for chatbot input guardrail rejections.
-- UUIDv7 PK for high-insert-rate transactional log per ARCH-1.7.1.
-- NO modified_at column (append-only, no set_modified_at() trigger applied).

-- Table: support_guardrail_rejections
CREATE TABLE IF NOT EXISTS support_guardrail_rejections (
    id              UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    session_id      UUID NOT NULL,
    rejection_reason VARCHAR(50) NOT NULL
                     CHECK (rejection_reason IN ('TOO_LONG', 'PROMPT_INJECTION', 'OFF_TOPIC')),
    message_hash    CHAR(64) NOT NULL,  -- SHA-256 hex (NOT raw message per ARCH-32 PII requirements)
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_sgr_session_id ON support_guardrail_rejections (session_id);
CREATE INDEX IF NOT EXISTS idx_sgr_created_at ON support_guardrail_rejections (created_at DESC);

-- Note: No modified_at column or set_modified_at() trigger — this is an append-only log table
-- (pattern established in V2: billing_cdr_events, billing_audit_log, billing_transactions)
