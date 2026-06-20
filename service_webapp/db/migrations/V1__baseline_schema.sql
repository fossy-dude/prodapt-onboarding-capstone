-- V1 Baseline Schema: all domains, all tables, indexes, FK constraints.
-- Runs as sboai_flyway. Extensions already installed by postgres init scripts.
-- DO NOT include CREATE EXTENSION here.
--
-- UUID strategy (ARCH-1.7.1 §1.7.1 overrides §1.11.2):
--   UUIDv7 (uuid_generate_v7()): transactional / high-insert-rate tables
--   UUIDv4 (gen_random_uuid()):  reference / config tables
--
-- All tables: created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
-- Most tables: modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL  (V2 trigger applies)
-- Exceptions: billing_cdr_events, billing_audit_log (append-only; no modified_at)

-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE cdr_type_enum AS ENUM ('voice', 'sms', 'data');
CREATE TYPE cdr_status_enum AS ENUM ('pending', 'rated', 'failed');
CREATE TYPE call_direction_enum AS ENUM ('MO', 'MT');
CREATE TYPE call_status_enum AS ENUM ('answered', 'no_answer', 'busy', 'failed');
CREATE TYPE sms_status_enum AS ENUM ('delivered', 'failed', 'pending');
CREATE TYPE network_type_enum AS ENUM ('2G', '3G', '4G', '5G');
CREATE TYPE subscriber_status_enum AS ENUM ('active', 'suspended', 'terminated');

-- ============================================================
-- IDENTITY DOMAIN
-- ============================================================

-- Subscriber master record (UUIDv4: created at registration, not a transaction stream)
CREATE TABLE identity_subscribers (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    msisdn          VARCHAR(15) NOT NULL,
    subscriber_name VARCHAR(200) NOT NULL,
    email           VARCHAR(255),
    status          subscriber_status_enum NOT NULL DEFAULT 'active',
    cognito_user_id VARCHAR(200),
    plan_id         UUID,  -- FK to plans_plans; added after plans table
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_identity_subscribers_msisdn UNIQUE (msisdn),
    CONSTRAINT uq_identity_subscribers_cognito_user_id UNIQUE (cognito_user_id)
);

CREATE INDEX idx_identity_subscribers_plan_id ON identity_subscribers (plan_id);
-- Trigram index for MSISDN fuzzy search (uses pg_trgm extension)
CREATE INDEX idx_identity_subscribers_msisdn_trgm ON identity_subscribers USING GIN (msisdn gin_trgm_ops);

-- SIM/KYC registration events (UUIDv7: transactional)
CREATE TABLE identity_registrations (
    id                UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
    registration_type VARCHAR(30) NOT NULL,
    operator_circle   VARCHAR(50),
    sim_serial        VARCHAR(50),
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    submitted_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_identity_registrations_subscriber_id ON identity_registrations (subscriber_id);

-- KYC submission records (UUIDv7: transactional)
CREATE TABLE identity_kyc_records (
    id                       UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id            UUID NOT NULL REFERENCES identity_subscribers (id),
    document_type            VARCHAR(30) NOT NULL,
    document_number_encrypted BYTEA NOT NULL,  -- AES-256 via pgcrypto
    kyc_status               VARCHAR(20) NOT NULL DEFAULT 'pending',
    verified_at              TIMESTAMPTZ,
    created_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at              TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_identity_kyc_records_subscriber_id ON identity_kyc_records (subscriber_id);

-- TRAI CAF submissions (UUIDv4: reference/admin record)
CREATE TABLE identity_caf_submissions (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id  UUID NOT NULL REFERENCES identity_subscribers (id),
    kyc_record_id  UUID NOT NULL REFERENCES identity_kyc_records (id),
    caf_reference  VARCHAR(50),
    submission_date DATE NOT NULL,
    operator_circle VARCHAR(50),
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_identity_caf_submissions_subscriber_id ON identity_caf_submissions (subscriber_id);
CREATE INDEX idx_identity_caf_submissions_kyc_record_id ON identity_caf_submissions (kyc_record_id);

-- ============================================================
-- PLANS DOMAIN
-- ============================================================

-- Plan catalogue (UUIDv4: seeded once; low churn)
CREATE TABLE plans_plans (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    plan_name     VARCHAR(100) NOT NULL,
    plan_code     VARCHAR(20) NOT NULL,
    price_paise   BIGINT NOT NULL,
    validity_days INT NOT NULL,
    data_limit_mb BIGINT,      -- NULL = unlimited
    voice_minutes INT,         -- NULL = unlimited
    sms_count     INT,         -- NULL = unlimited
    is_active     BOOL NOT NULL DEFAULT TRUE,
    description   TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_plans_plans_plan_name UNIQUE (plan_name),
    CONSTRAINT uq_plans_plans_plan_code UNIQUE (plan_code)
);

-- Active subscriptions (UUIDv4: reference/join record)
CREATE TABLE plans_subscriptions (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
    plan_id       UUID NOT NULL REFERENCES plans_plans (id),
    start_date    TIMESTAMPTZ NOT NULL,
    end_date      TIMESTAMPTZ,
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_plans_subscriptions_subscriber_id ON plans_subscriptions (subscriber_id);
CREATE INDEX idx_plans_subscriptions_plan_id ON plans_subscriptions (plan_id);

-- Per-plan config overrides (UUIDv4: configuration)
CREATE TABLE plans_plan_config (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    plan_id      UUID NOT NULL REFERENCES plans_plans (id),
    config_key   VARCHAR(100) NOT NULL,
    config_value TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_plans_plan_config_plan_key UNIQUE (plan_id, config_key)
);

CREATE INDEX idx_plans_plan_config_plan_id ON plans_plan_config (plan_id);

-- Back-fill FK from identity_subscribers → plans_plans
ALTER TABLE identity_subscribers
    ADD CONSTRAINT fk_identity_subscribers_plan_id
    FOREIGN KEY (plan_id) REFERENCES plans_plans (id);

-- ============================================================
-- BILLING DOMAIN
-- ============================================================

-- Wallet balance per subscriber (UUIDv4: one row per subscriber, not a transaction log)
CREATE TABLE billing_wallet_balances (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id       UUID NOT NULL REFERENCES identity_subscribers (id),
    msisdn              VARCHAR(15) NOT NULL,  -- denormalised for fast Valkey warm-up query
    balance_paise       BIGINT NOT NULL DEFAULT 0,
    last_recharge_at    TIMESTAMPTZ,
    last_deduction_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_billing_wallet_balances_subscriber_id UNIQUE (subscriber_id),
    CONSTRAINT uq_billing_wallet_balances_msisdn UNIQUE (msisdn)
);

-- CDR events (UUIDv7: 5M+ rows; high insert rate — see docs/Schema - CDR.md)
-- Append-only: no modified_at; V2 trigger NOT applied to this table.
CREATE TABLE billing_cdr_events (
    id               UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    session_id       UUID NOT NULL,
    subscriber_id    UUID NOT NULL REFERENCES identity_subscribers (id),
    cdr_type         cdr_type_enum NOT NULL,
    telecom_circle   VARCHAR(50) NOT NULL,
    cell_tower_id    VARCHAR(100),
    roaming          BOOL NOT NULL DEFAULT FALSE,
    cost_paise       BIGINT NOT NULL DEFAULT 0,
    status           cdr_status_enum NOT NULL DEFAULT 'pending',
    fraud_flag       BOOL NOT NULL DEFAULT FALSE,
    start_time       TIMESTAMPTZ NOT NULL,
    end_time         TIMESTAMPTZ,
    -- Voice-specific columns (NULL for sms, data)
    from_number      VARCHAR(20),
    to_number        VARCHAR(20),
    call_direction   call_direction_enum,
    duration_seconds INT,
    call_status      call_status_enum,
    -- SMS-specific columns (NULL for voice, data)
    message_direction call_direction_enum,
    sms_status        sms_status_enum,
    -- Data-specific columns (NULL for voice, sms)
    network_type     network_type_enum,
    downloaded_mb    NUMERIC(10,3),
    uploaded_mb      NUMERIC(10,3),
    volume_mb        NUMERIC(10,3),
    apn              VARCHAR(100),
    imei             VARCHAR(20),
    operator_id      VARCHAR(50),
    created_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
    -- No modified_at: append-only immutable table (ARCH-1.7.1)
);

CREATE INDEX idx_billing_cdr_events_subscriber_id ON billing_cdr_events (subscriber_id);
CREATE INDEX idx_billing_cdr_events_session_id ON billing_cdr_events (session_id);
CREATE INDEX idx_billing_cdr_events_status ON billing_cdr_events (status);
CREATE INDEX idx_billing_cdr_events_start_time ON billing_cdr_events (start_time);
CREATE INDEX idx_billing_cdr_events_cdr_type ON billing_cdr_events (cdr_type);

-- Payment and deduction transactions (UUIDv7: high insert rate)
CREATE TABLE billing_transactions (
    id                   UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id        UUID NOT NULL REFERENCES identity_subscribers (id),
    transaction_type     VARCHAR(20) NOT NULL,
    amount_paise         BIGINT NOT NULL,
    reference_type       VARCHAR(20),
    reference_id         UUID,
    description          TEXT,
    balance_before_paise BIGINT NOT NULL,
    balance_after_paise  BIGINT NOT NULL,
    created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_billing_transactions_subscriber_id ON billing_transactions (subscriber_id);
CREATE INDEX idx_billing_transactions_reference_id ON billing_transactions (reference_id);

-- Audit log (UUIDv7; append-only; no modified_at; INSERT only via app role)
-- Retained 6 years; archived to S3 after 2 years (ARCH-1.7.1)
CREATE TABLE billing_audit_log (
    id             UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    entity_type    VARCHAR(50) NOT NULL,
    entity_id      UUID NOT NULL,
    action         VARCHAR(20) NOT NULL,
    actor_id       VARCHAR(200),
    actor_type     VARCHAR(20),
    old_value      JSONB,
    new_value      JSONB,
    ip_address     INET,
    correlation_id UUID,
    created_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL
    -- No modified_at: append-only table (ARCH-1.7.1)
);

CREATE INDEX idx_billing_audit_log_entity_id ON billing_audit_log (entity_id);
CREATE INDEX idx_billing_audit_log_entity_type ON billing_audit_log (entity_type);
CREATE INDEX idx_billing_audit_log_created_at ON billing_audit_log (created_at);

-- ============================================================
-- RECHARGE DOMAIN
-- ============================================================

-- Tokenised payment methods (UUIDv4: config/reference)
CREATE TABLE recharge_payment_methods (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
    method_type   VARCHAR(20) NOT NULL,   -- card, upi, netbanking, wallet
    token         VARCHAR(200) NOT NULL,  -- PCI-DSS tokenised reference; raw PAN never stored
    last_four     VARCHAR(4),
    is_default    BOOL NOT NULL DEFAULT FALSE,
    is_active     BOOL NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_recharge_payment_methods_subscriber_id ON recharge_payment_methods (subscriber_id);

-- Recharge orders (UUIDv7: transactional)
CREATE TABLE recharge_orders (
    id                UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
    plan_id           UUID NOT NULL REFERENCES plans_plans (id),
    amount_paise      BIGINT NOT NULL,
    idempotency_key   VARCHAR(100),
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    payment_method_id UUID REFERENCES recharge_payment_methods (id),
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_recharge_orders_idempotency_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_recharge_orders_subscriber_id ON recharge_orders (subscriber_id);
CREATE INDEX idx_recharge_orders_plan_id ON recharge_orders (plan_id);
CREATE INDEX idx_recharge_orders_status ON recharge_orders (status);

-- PDF receipts (UUIDv4: one-per-order reference record)
CREATE TABLE recharge_receipts (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    recharge_order_id  UUID NOT NULL REFERENCES recharge_orders (id),
    receipt_number     VARCHAR(50) NOT NULL,
    s3_key             VARCHAR(500),
    generated_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_recharge_receipts_order_id UNIQUE (recharge_order_id),
    CONSTRAINT uq_recharge_receipts_number UNIQUE (receipt_number)
);

-- ============================================================
-- NOTIFICATIONS DOMAIN
-- ============================================================

-- Notification event log (UUIDv7: high insert rate)
CREATE TABLE notifications_events (
    id                UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
    notification_type VARCHAR(50) NOT NULL,
    channel           VARCHAR(20) NOT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    payload           JSONB,
    sent_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_notifications_events_subscriber_id ON notifications_events (subscriber_id);
CREATE INDEX idx_notifications_events_status ON notifications_events (status);

-- Notification type configuration (UUIDv4: config)
CREATE TABLE notifications_config (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    notification_type VARCHAR(50) NOT NULL,
    template_text     TEXT,
    threshold_value   BIGINT,
    is_active         BOOL NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_notifications_config_type UNIQUE (notification_type)
);

-- Per-subscriber channel preferences (UUIDv4: config)
CREATE TABLE notifications_preferences (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
    notification_type VARCHAR(50) NOT NULL,
    channel           VARCHAR(20) NOT NULL,
    is_enabled        BOOL NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_notifications_preferences_subscriber_type_channel
        UNIQUE (subscriber_id, notification_type, channel)
);

CREATE INDEX idx_notifications_preferences_subscriber_id ON notifications_preferences (subscriber_id);

-- ============================================================
-- SUPPORT DOMAIN
-- ============================================================

-- Support tickets (UUIDv7: transactional)
CREATE TABLE support_tickets (
    id            UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
    category      VARCHAR(50) NOT NULL,
    subject       VARCHAR(200) NOT NULL,
    description   TEXT NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'open',
    priority      VARCHAR(10) NOT NULL DEFAULT 'medium',
    assigned_to   VARCHAR(200),
    resolved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_support_tickets_subscriber_id ON support_tickets (subscriber_id);
CREATE INDEX idx_support_tickets_status ON support_tickets (status);

-- Chat sessions (UUIDv7: transactional)
CREATE TABLE support_chat_sessions (
    id            UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
    ticket_id     UUID REFERENCES support_tickets (id),
    session_type  VARCHAR(20) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    started_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    ended_at      TIMESTAMPTZ,
    message_count INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_support_chat_sessions_subscriber_id ON support_chat_sessions (subscriber_id);
CREATE INDEX idx_support_chat_sessions_ticket_id ON support_chat_sessions (ticket_id);

-- Session learnings for RAG (UUIDv4: reference/config)
CREATE TABLE support_session_learnings (
    id                   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id           UUID NOT NULL REFERENCES support_chat_sessions (id),
    learning_type        VARCHAR(50) NOT NULL,
    content              TEXT NOT NULL,
    vector_embedding_id  VARCHAR(200),  -- Milvus collection reference
    created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_support_session_learnings_session_id ON support_session_learnings (session_id);

-- ============================================================
-- FRAUD DOMAIN
-- ============================================================

-- Fraud rule definitions (UUIDv4: manually managed; low churn)
CREATE TABLE fraud_rules (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    rule_name   VARCHAR(100) NOT NULL,
    rule_type   VARCHAR(50) NOT NULL,
    conditions  JSONB NOT NULL,
    severity    VARCHAR(10) NOT NULL DEFAULT 'medium',
    is_active   BOOL NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_fraud_rules_name UNIQUE (rule_name)
);

-- Fraud cases (UUIDv7: transactional)
CREATE TABLE fraud_cases (
    id           UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
    fraud_type   VARCHAR(50) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'open',
    risk_score   NUMERIC(5,4),
    triggered_by VARCHAR(50),
    rule_id      UUID REFERENCES fraud_rules (id),
    evidence     JSONB,
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_fraud_cases_subscriber_id ON fraud_cases (subscriber_id);
CREATE INDEX idx_fraud_cases_status ON fraud_cases (status);
CREATE INDEX idx_fraud_cases_rule_id ON fraud_cases (rule_id);

-- Blacklisted subscribers (UUIDv7: transactional; one row per blacklist event)
CREATE TABLE fraud_blacklist (
    id              UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id   UUID NOT NULL REFERENCES identity_subscribers (id),
    reason          TEXT NOT NULL,
    fraud_case_id   UUID REFERENCES fraud_cases (id),
    blacklisted_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_fraud_blacklist_subscriber_id UNIQUE (subscriber_id)
);

CREATE INDEX idx_fraud_blacklist_subscriber_id ON fraud_blacklist (subscriber_id);
CREATE INDEX idx_fraud_blacklist_fraud_case_id ON fraud_blacklist (fraud_case_id);

-- ============================================================
-- SEGMENTATION DOMAIN
-- ============================================================

-- Rule definitions for segment classification (UUIDv4: config)
CREATE TABLE segmentation_segment_rules (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    rule_name       VARCHAR(100) NOT NULL,
    rule_description TEXT,
    conditions      JSONB NOT NULL,
    segment_label   VARCHAR(100) NOT NULL,
    is_active       BOOL NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_segmentation_segment_rules_name UNIQUE (rule_name)
);

-- LLM-assigned segment labels (UUIDv7: batch-written; high volume)
CREATE TABLE segmentation_labels (
    id             UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id  UUID NOT NULL REFERENCES identity_subscribers (id),
    segment_label  VARCHAR(100) NOT NULL,
    confidence_score NUMERIC(5,4),
    labeled_by     VARCHAR(50),
    labeled_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_segmentation_labels_subscriber_id ON segmentation_labels (subscriber_id);
CREATE INDEX idx_segmentation_labels_segment_label ON segmentation_labels (segment_label);

-- Plan recommendation feedback (UUIDv7: real-time events)
CREATE TABLE segmentation_recommendation_feedback (
    id                   UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id        UUID NOT NULL REFERENCES identity_subscribers (id),
    recommendation_type  VARCHAR(50) NOT NULL,
    recommended_plan_id  UUID REFERENCES plans_plans (id),
    action_taken         VARCHAR(20),
    feedback_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_segmentation_recommendation_feedback_subscriber_id
    ON segmentation_recommendation_feedback (subscriber_id);

-- Upsell response events (UUIDv7: real-time events)
CREATE TABLE segmentation_upsell_feedback (
    id              UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    subscriber_id   UUID NOT NULL REFERENCES identity_subscribers (id),
    upsell_offer_id UUID,
    offer_plan_id   UUID REFERENCES plans_plans (id),
    response        VARCHAR(20),
    responded_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_segmentation_upsell_feedback_subscriber_id
    ON segmentation_upsell_feedback (subscriber_id);

-- ============================================================
-- OPS DOMAIN
-- ============================================================

-- Order fulfilment tracking (UUIDv4: operational record)
CREATE TABLE ops_order_fulfilment (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
    plan_id           UUID NOT NULL REFERENCES plans_plans (id),
    recharge_order_id UUID REFERENCES recharge_orders (id),
    fulfilment_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    fulfilment_type   VARCHAR(20) NOT NULL,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_ops_order_fulfilment_subscriber_id ON ops_order_fulfilment (subscriber_id);
CREATE INDEX idx_ops_order_fulfilment_plan_id ON ops_order_fulfilment (plan_id);
CREATE INDEX idx_ops_order_fulfilment_recharge_order_id ON ops_order_fulfilment (recharge_order_id);

-- ML forecast results (UUIDv4: analytical output)
CREATE TABLE ops_forecast_results (
    id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    forecast_type         VARCHAR(50) NOT NULL,
    forecast_period_start DATE NOT NULL,
    forecast_period_end   DATE NOT NULL,
    model_version         VARCHAR(50),
    predictions           JSONB NOT NULL,
    accuracy_score        NUMERIC(5,4),
    created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ============================================================
-- SOP DOMAIN
-- ============================================================

-- SOP agent rules (UUIDv4: seeded; rarely updated)
CREATE TABLE sop_rules (
    id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    rule_name         VARCHAR(100) NOT NULL,
    domain            VARCHAR(50) NOT NULL,
    trigger_condition TEXT NOT NULL,
    response_template TEXT NOT NULL,
    priority          INT NOT NULL DEFAULT 0,
    is_active         BOOL NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_sop_rules_name UNIQUE (rule_name)
);

-- Knowledge base chunks for RAG (UUIDv4: seeded)
CREATE TABLE sop_knowledge_chunks (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    source_document     VARCHAR(200),
    chunk_text          TEXT NOT NULL,
    vector_embedding_id VARCHAR(200),  -- Milvus collection reference
    chunk_index         INT NOT NULL,
    domain              VARCHAR(50),
    created_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_sop_knowledge_chunks_domain ON sop_knowledge_chunks (domain);
