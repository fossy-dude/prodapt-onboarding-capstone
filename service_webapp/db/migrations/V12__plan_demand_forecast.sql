-- V12: Plan demand forecast cache table (Story 7.4).
-- Creates forecast_results if Story 7.3's V11 has not yet run, then
-- adds plan_demand-specific columns unconditionally (IF NOT EXISTS is idempotent).
-- UUID strategy: UUIDv7 (high-insert cache table).

CREATE TABLE IF NOT EXISTS forecast_results (
    id            UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    forecast_type VARCHAR(50) NOT NULL,
    forecast_date DATE NOT NULL,
    model_version VARCHAR(50),
    trained_at    TIMESTAMPTZ,
    valid_until   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Plan-demand columns (nullable; NULL for subscriber-level forecasts from Story 7.3)
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS plan_id              UUID;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS plan_name            VARCHAR(200);
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_uptake_30d INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_uptake_60d INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_uptake_90d INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS uptake_trend_90d     JSONB;

-- Unique constraint: one row per forecast_type + date + plan (NULL plan = subscriber-level)
-- Use a partial unique index so NULL plan_id rows are also deduplicated correctly.
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_results_plan_demand
    ON forecast_results (forecast_type, forecast_date, plan_id)
    WHERE plan_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_results_subscriber_level
    ON forecast_results (forecast_type, forecast_date)
    WHERE plan_id IS NULL;

-- Efficient lookup: active plan forecasts by type
CREATE INDEX IF NOT EXISTS idx_forecast_results_type_plan_valid
    ON forecast_results (forecast_type, plan_id, valid_until);

-- Index to support billing_audit_log queries for recharge events
CREATE INDEX IF NOT EXISTS idx_recharge_orders_completed_at
    ON recharge_orders (completed_at)
    WHERE completed_at IS NOT NULL;
