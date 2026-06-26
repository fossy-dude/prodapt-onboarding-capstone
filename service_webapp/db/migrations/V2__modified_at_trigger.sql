-- V2: set_modified_at() trigger function and application to every table that has modified_at.
-- Tables without modified_at are excluded:
--   billing_cdr_events   — append-only CDR stream
--   billing_audit_log    — append-only audit trail
--   billing_transactions — append-only ledger (corrections use offsetting rows)
--
-- Idempotent: DROP TRIGGER IF EXISTS before each CREATE allows safe re-run after flyway repair.

CREATE OR REPLACE FUNCTION set_modified_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$;

-- identity domain
DROP TRIGGER IF EXISTS trg_identity_subscribers_modified_at ON identity_subscribers;
CREATE TRIGGER trg_identity_subscribers_modified_at
    BEFORE UPDATE ON identity_subscribers
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_identity_registrations_modified_at ON identity_registrations;
CREATE TRIGGER trg_identity_registrations_modified_at
    BEFORE UPDATE ON identity_registrations
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_identity_kyc_records_modified_at ON identity_kyc_records;
CREATE TRIGGER trg_identity_kyc_records_modified_at
    BEFORE UPDATE ON identity_kyc_records
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_identity_caf_submissions_modified_at ON identity_caf_submissions;
CREATE TRIGGER trg_identity_caf_submissions_modified_at
    BEFORE UPDATE ON identity_caf_submissions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- plans domain
DROP TRIGGER IF EXISTS trg_plans_plans_modified_at ON plans_plans;
CREATE TRIGGER trg_plans_plans_modified_at
    BEFORE UPDATE ON plans_plans
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_plans_subscriptions_modified_at ON plans_subscriptions;
CREATE TRIGGER trg_plans_subscriptions_modified_at
    BEFORE UPDATE ON plans_subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_plans_plan_config_modified_at ON plans_plan_config;
CREATE TRIGGER trg_plans_plan_config_modified_at
    BEFORE UPDATE ON plans_plan_config
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- billing domain (NOT applied to billing_cdr_events, billing_audit_log, or billing_transactions — all append-only)
DROP TRIGGER IF EXISTS trg_billing_wallet_balances_modified_at ON billing_wallet_balances;
CREATE TRIGGER trg_billing_wallet_balances_modified_at
    BEFORE UPDATE ON billing_wallet_balances
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- recharge domain
DROP TRIGGER IF EXISTS trg_recharge_payment_methods_modified_at ON recharge_payment_methods;
CREATE TRIGGER trg_recharge_payment_methods_modified_at
    BEFORE UPDATE ON recharge_payment_methods
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_recharge_orders_modified_at ON recharge_orders;
CREATE TRIGGER trg_recharge_orders_modified_at
    BEFORE UPDATE ON recharge_orders
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_recharge_receipts_modified_at ON recharge_receipts;
CREATE TRIGGER trg_recharge_receipts_modified_at
    BEFORE UPDATE ON recharge_receipts
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- notifications domain
DROP TRIGGER IF EXISTS trg_notifications_events_modified_at ON notifications_events;
CREATE TRIGGER trg_notifications_events_modified_at
    BEFORE UPDATE ON notifications_events
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_notifications_config_modified_at ON notifications_config;
CREATE TRIGGER trg_notifications_config_modified_at
    BEFORE UPDATE ON notifications_config
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_notifications_preferences_modified_at ON notifications_preferences;
CREATE TRIGGER trg_notifications_preferences_modified_at
    BEFORE UPDATE ON notifications_preferences
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- support domain
DROP TRIGGER IF EXISTS trg_support_tickets_modified_at ON support_tickets;
CREATE TRIGGER trg_support_tickets_modified_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_support_chat_sessions_modified_at ON support_chat_sessions;
CREATE TRIGGER trg_support_chat_sessions_modified_at
    BEFORE UPDATE ON support_chat_sessions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_support_session_learnings_modified_at ON support_session_learnings;
CREATE TRIGGER trg_support_session_learnings_modified_at
    BEFORE UPDATE ON support_session_learnings
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- fraud domain
DROP TRIGGER IF EXISTS trg_fraud_rules_modified_at ON fraud_rules;
CREATE TRIGGER trg_fraud_rules_modified_at
    BEFORE UPDATE ON fraud_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_fraud_cases_modified_at ON fraud_cases;
CREATE TRIGGER trg_fraud_cases_modified_at
    BEFORE UPDATE ON fraud_cases
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_fraud_blacklist_modified_at ON fraud_blacklist;
CREATE TRIGGER trg_fraud_blacklist_modified_at
    BEFORE UPDATE ON fraud_blacklist
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- segmentation domain
DROP TRIGGER IF EXISTS trg_segmentation_segment_rules_modified_at ON segmentation_segment_rules;
CREATE TRIGGER trg_segmentation_segment_rules_modified_at
    BEFORE UPDATE ON segmentation_segment_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_segmentation_labels_modified_at ON segmentation_labels;
CREATE TRIGGER trg_segmentation_labels_modified_at
    BEFORE UPDATE ON segmentation_labels
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_segmentation_recommendation_feedback_modified_at ON segmentation_recommendation_feedback;
CREATE TRIGGER trg_segmentation_recommendation_feedback_modified_at
    BEFORE UPDATE ON segmentation_recommendation_feedback
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_segmentation_upsell_feedback_modified_at ON segmentation_upsell_feedback;
CREATE TRIGGER trg_segmentation_upsell_feedback_modified_at
    BEFORE UPDATE ON segmentation_upsell_feedback
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- ops domain
DROP TRIGGER IF EXISTS trg_ops_order_fulfilment_modified_at ON ops_order_fulfilment;
CREATE TRIGGER trg_ops_order_fulfilment_modified_at
    BEFORE UPDATE ON ops_order_fulfilment
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_ops_forecast_results_modified_at ON ops_forecast_results;
CREATE TRIGGER trg_ops_forecast_results_modified_at
    BEFORE UPDATE ON ops_forecast_results
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- sop domain
DROP TRIGGER IF EXISTS trg_sop_rules_modified_at ON sop_rules;
CREATE TRIGGER trg_sop_rules_modified_at
    BEFORE UPDATE ON sop_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

DROP TRIGGER IF EXISTS trg_sop_knowledge_chunks_modified_at ON sop_knowledge_chunks;
CREATE TRIGGER trg_sop_knowledge_chunks_modified_at
    BEFORE UPDATE ON sop_knowledge_chunks
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();
