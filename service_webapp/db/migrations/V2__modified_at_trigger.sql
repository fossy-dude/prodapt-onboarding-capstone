-- V2: set_modified_at() trigger function and application to every table that has modified_at.
-- Tables without modified_at (billing_cdr_events, billing_audit_log) are excluded.

CREATE OR REPLACE FUNCTION set_modified_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$;

-- identity domain
CREATE TRIGGER trg_identity_subscribers_modified_at
    BEFORE UPDATE ON identity_subscribers
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_identity_registrations_modified_at
    BEFORE UPDATE ON identity_registrations
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_identity_kyc_records_modified_at
    BEFORE UPDATE ON identity_kyc_records
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_identity_caf_submissions_modified_at
    BEFORE UPDATE ON identity_caf_submissions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- plans domain
CREATE TRIGGER trg_plans_plans_modified_at
    BEFORE UPDATE ON plans_plans
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_plans_subscriptions_modified_at
    BEFORE UPDATE ON plans_subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_plans_plan_config_modified_at
    BEFORE UPDATE ON plans_plan_config
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- billing domain (NOT applied to billing_cdr_events or billing_audit_log — append-only)
CREATE TRIGGER trg_billing_wallet_balances_modified_at
    BEFORE UPDATE ON billing_wallet_balances
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_billing_transactions_modified_at
    BEFORE UPDATE ON billing_transactions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- recharge domain
CREATE TRIGGER trg_recharge_payment_methods_modified_at
    BEFORE UPDATE ON recharge_payment_methods
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_recharge_orders_modified_at
    BEFORE UPDATE ON recharge_orders
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_recharge_receipts_modified_at
    BEFORE UPDATE ON recharge_receipts
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- notifications domain
CREATE TRIGGER trg_notifications_events_modified_at
    BEFORE UPDATE ON notifications_events
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_notifications_config_modified_at
    BEFORE UPDATE ON notifications_config
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_notifications_preferences_modified_at
    BEFORE UPDATE ON notifications_preferences
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- support domain
CREATE TRIGGER trg_support_tickets_modified_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_support_chat_sessions_modified_at
    BEFORE UPDATE ON support_chat_sessions
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_support_session_learnings_modified_at
    BEFORE UPDATE ON support_session_learnings
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- fraud domain
CREATE TRIGGER trg_fraud_rules_modified_at
    BEFORE UPDATE ON fraud_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_fraud_cases_modified_at
    BEFORE UPDATE ON fraud_cases
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_fraud_blacklist_modified_at
    BEFORE UPDATE ON fraud_blacklist
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- segmentation domain
CREATE TRIGGER trg_segmentation_segment_rules_modified_at
    BEFORE UPDATE ON segmentation_segment_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_segmentation_labels_modified_at
    BEFORE UPDATE ON segmentation_labels
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_segmentation_recommendation_feedback_modified_at
    BEFORE UPDATE ON segmentation_recommendation_feedback
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_segmentation_upsell_feedback_modified_at
    BEFORE UPDATE ON segmentation_upsell_feedback
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- ops domain
CREATE TRIGGER trg_ops_order_fulfilment_modified_at
    BEFORE UPDATE ON ops_order_fulfilment
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_ops_forecast_results_modified_at
    BEFORE UPDATE ON ops_forecast_results
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

-- sop domain
CREATE TRIGGER trg_sop_rules_modified_at
    BEFORE UPDATE ON sop_rules
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();

CREATE TRIGGER trg_sop_knowledge_chunks_modified_at
    BEFORE UPDATE ON sop_knowledge_chunks
    FOR EACH ROW EXECUTE FUNCTION set_modified_at();
