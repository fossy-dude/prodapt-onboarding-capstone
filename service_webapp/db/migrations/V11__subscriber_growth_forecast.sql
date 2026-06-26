-- V11: Subscriber growth forecast cache table (Story 7.3).
--
-- Creates the shared forecast_results cache table. Story 7.4's V12 extends this same
-- table with plan_demand columns (predicted_uptake_*, uptake_trend_90d, plan_id,
-- plan_name); the two forecast types coexist via forecast_type, with type-specific
-- columns NULL for the other type. V12 is written defensively ("CREATE TABLE IF NOT
-- EXISTS ... if Story 7.3's V11 has not yet run"), so this migration owns the base
-- CREATE and V12 only ALTERs.
--
-- Subscriber-growth rows store per-day activations/churn projections with 95%
-- confidence intervals plus a generic metrics JSONB (MAPE) so cache hits can return
-- the same quality metrics as a fresh forecast.
--
-- UUID strategy: UUIDv7 (high-insert cache table) — matches V12 and the rest of the
-- ops domain. Runs as sboai_flyway; pg_uuidv7 / pgcrypto already provisioned by
-- 01_extensions.sql (migrations must NOT CREATE EXTENSION).

CREATE TABLE IF NOT EXISTS forecast_results (
    id            UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
    forecast_type VARCHAR(50) NOT NULL,
    forecast_date DATE NOT NULL,
    model_version VARCHAR(50),
    trained_at    TIMESTAMPTZ,
    valid_until   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Subscriber-growth columns (nullable; NULL for plan-demand rows from Story 7.4).
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_activations  INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS predicted_churn         INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS lower_bound_activations INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS upper_bound_activations INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS lower_bound_churn       INTEGER;
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS upper_bound_churn       INTEGER;

-- Generic quality-metrics blob (e.g. {mape_activations, mape_churn, ...}). Nullable
-- so plan-demand rows (Story 7.4) and future forecast types can ignore it.
ALTER TABLE forecast_results ADD COLUMN IF NOT EXISTS metrics JSONB;

-- Cache read: WHERE forecast_type = %s AND valid_until > NOW() ORDER BY forecast_date.
-- Plain (non-partial) index so it does not depend on plan_id (added by V12).
CREATE INDEX IF NOT EXISTS idx_forecast_results_type_date
    ON forecast_results (forecast_type, forecast_date);

-- App role manages the cache (DELETE on retrain + INSERT + SELECT). Runs as
-- sboai_flyway; idempotent DO block (V5 lesson) skips cleanly if sboai_app is absent.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'sboai_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON forecast_results TO sboai_app';
    ELSE
        RAISE NOTICE 'sboai_app role missing — forecast_results grants skipped (run 02_roles.sh first)';
    END IF;
END
$$;
