-- Story 4.1: Notification threshold configuration table
-- Stores operational parameters for notification triggers
-- low_balance_threshold_paise: balance threshold in paise for LOW_BALANCE notifications (default 1000 = ₹10)
-- plan_expiry_reminder_days: days before expiry to send PLAN_EXPIRY_REMINDER (default 3)

-- Create notification_threshold_config table
CREATE TABLE IF NOT EXISTS notification_threshold_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Apply the set_modified_at() trigger (defined in V2__modified_at_trigger.sql)
DROP TRIGGER IF EXISTS trg_notification_threshold_config_modified_at ON notification_threshold_config;
CREATE TRIGGER trg_notification_threshold_config_modified_at
    BEFORE UPDATE ON notification_threshold_config
    FOR EACH ROW
    EXECUTE FUNCTION set_modified_at();

-- Seed default configuration values (idempotent)
INSERT INTO notification_threshold_config (key, value)
VALUES
    ('low_balance_threshold_paise', '1000'),
    ('plan_expiry_reminder_days', '3'),
    ('rate_limit_rpm', '100')
ON CONFLICT (key) DO NOTHING;

-- Add comment for documentation
COMMENT ON TABLE notification_threshold_config IS 'Stores operational parameters for notification triggers (thresholds, lead times, etc.)';
COMMENT ON COLUMN notification_threshold_config.key IS 'Configuration key (e.g., low_balance_threshold_paise, plan_expiry_reminder_days)';
COMMENT ON COLUMN notification_threshold_config.value IS 'Configuration value (stored as TEXT, parsed by application)';
