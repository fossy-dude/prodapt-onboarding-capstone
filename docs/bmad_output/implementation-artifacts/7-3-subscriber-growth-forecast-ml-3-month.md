---
baseline_commit: dd7e3df
---

# Story 7.3: Subscriber Growth Forecast (ML, 3-Month)

Status: review

## Story

As an **operations team member**,
I want a 3-month subscriber activation and churn forecast with confidence intervals,
so that I can plan network capacity and staffing ahead of demand.

## Acceptance Criteria

1. **Given** at least 90 days of historical activation data exists in Postgres, **When** GET /api/v1/ops/forecasts/subscriber-growth is called, **Then** the endpoint trains (or loads cached) a scikit-learn time-series model on daily activation and churn counts. [Source: epics.md:2008; FR-44]

2. **And** returns a 90-day projection: date, predicted_activations, predicted_churn, lower_bound, upper_bound (95% CI). [Source: epics.md:2010]

3. **And** MAPE < 15% on the most recent 30-day holdout period. [Source: epics.md:2012; NFR-14]

4. **And** the Forecasts.tsx chart renders the projection as a line chart with shaded confidence interval band (Recharts). [Source: epics.md:2014]

5. **And** the model is retrained daily via a scheduled job; results are cached in Postgres (forecast_results table). [Source: epics.md:2016]

6. **And** the forecast endpoint uses queries.py (SELECT only for reading cached results, INSERT for writing new forecasts) per CQRS rules. [Source: architecture.md:ARCH-4]

7. **And** role-based access control restricts the endpoint to users with role claim = 'ops' in JWT. [Source: architecture.md:103; JWT role-based auth]

## Tasks / Subtasks

- [x] **Task 1: Database schema for forecast cache** (AC: #1, #5, #6)
  - [x] Create Flyway migration `V__forecast_cache.sql`:
    - Table `forecast_results`:
      - `forecast_id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
      - `forecast_type` VARCHAR(50) NOT NULL (e.g., 'subscriber_growth')
      - `forecast_date` DATE NOT NULL (date for this prediction point)
      - `predicted_activations` INTEGER NOT NULL
      - `predicted_churn` INTEGER NOT NULL
      - `lower_bound_activations` INTEGER NOT NULL
      - `upper_bound_activations` INTEGER NOT NULL
      - `lower_bound_churn` INTEGER NOT NULL
      - `upper_bound_churn` INTEGER NOT NULL
      - `model_version` VARCHAR(50) NOT NULL
      - `trained_at` TIMESTAMP NOT NULL
      - `valid_until` TIMESTAMP NOT NULL (cache expiry, typically 24h)
      - `created_at` TIMESTAMP DEFAULT NOW()
    - Indexes: `(forecast_type, forecast_date)` for efficient range queries
    - Index: `(valid_until)` for cleanup job
  - [x] Run migration via `just migrate` (or tox env)

- [x] **Task 2: ML forecast model implementation** (AC: #1, #2, #3)
  - [x] Create `service_webapp/src/ops/forecasting/subscriber_growth_model.py`.
  - [x] Class `SubscriberGrowthForecaster`:
    - `__init__(self, model_type: str = "gradient_boosting")`: initialize scikit-learn model (GradientBoostingRegressor or LinearRegression as fallback)
    - `train(self, historical_data: pd.DataFrame) -> None`: fit model on daily activation/churn counts
      - Input DataFrame columns: `date, activations, churn`
      - Feature engineering: extract day_of_week, day_of_month, week_of_year for seasonality
      - Train separate models for activations and churn (or multi-output model)
    - `predict(self, horizon_days: int = 90) -> pd.DataFrame`:
      - Generate future dates from last historical date + horizon_days
      - Return DataFrame with: `date, predicted_activations, predicted_churn, lower_bound_activations, upper_bound_activations, lower_bound_churn, upper_bound_churn`
      - Confidence intervals: use scikit-learn's quantile regression or bootstrap method (95% CI = 2.5th-97.5th percentiles)
    - `evaluate(self, actual_data: pd.DataFrame) -> dict`:
      - Compute MAPE on holdout set: `mean(abs((actual - predicted) / actual)) * 100`
      - Return: `{"mape_activations": float, "mape_churn": float, "passed_mape_threshold": bool}`
  - [x] Model selection logic:
    - Try GradientBoostingRegressor (better for non-linear trends)
    - Fall back to LinearRegression if GradientBoosting fails or data is sparse
    - Log model choice and performance metrics

- [x] **Task 3: Database queries for forecast data** (AC: #1, #6)
  - [x] Add to `service_webapp/src/db/queries/ops_queries.py` (from Story 7.2):
    - Function `get_historical_activations_churn(db_conn, days_back: int = 180) -> list[dict]`:
      - Query: `SELECT DATE(created_at) as date, COUNT(*) as activations FROM subscribers WHERE created_at >= NOW() - INTERVAL ':days_back days' GROUP BY DATE(created_at) ORDER BY date`
      - For churn: use a proxy (e.g., last_activity_at < NOW() - INTERVAL '90 days' AND status = 'ACTIVE') or actual churn if tracked
      - Return: list of `{"date": date, "activations": int, "churn": int}`
    - Function `get_cached_forecast(db_conn, forecast_type: str = "subscriber_growth") -> list[dict]`:
      - Query: `SELECT * FROM forecast_results WHERE forecast_type = :forecast_type AND valid_until > NOW() ORDER BY forecast_date`
      - Return list of forecast rows or empty list if cache expired/missing
    - Function `save_forecast_results(db_conn, forecast_df: pd.DataFrame, model_version: str, valid_hours: int = 24) -> None`:
      - Delete old cache: `DELETE FROM forecast_results WHERE forecast_type = 'subscriber_growth'`
      - Insert new rows: batch INSERT from DataFrame
      - Set `valid_until = NOW() + INTERVAL ':valid_hours hours'`

- [x] **Task 4: FastAPI endpoint for subscriber growth forecast** (AC: #1, #2, #3, #6, #7)
  - [x] Add to `service_webapp/src/api/v1/ops.py` (from Story 7.2):
    - Endpoint `GET /api/v1/ops/forecasts/subscriber-growth`:
      - Auth dependency: `require_role("ops")`
      - Logic:
        1. Check cached forecast via `get_cached_forecast(db_conn)`
        2. If cache valid (not expired), return cached data immediately
        3. If cache expired/missing:
           - Fetch historical data via `get_historical_activations_churn(db_conn, days_back=180)`
           - Validate: require at least 90 days of data, else return 400 "Insufficient historical data"
           - Train model via `SubscriberGrowthForecaster.train()`
           - Evaluate on last 30 days: assert MAPE < 15%, else log warning but still return (soft gate, eval harness enforces hard gate)
           - Generate 90-day forecast via `predict(horizon_days=90)`
           - Cache results via `save_forecast_results(db_conn, forecast_df, model_version)`
           - Return forecast data
      - Return JSON: `{"forecasts": [{"date": "2026-07-01", "predicted_activations": 150, "predicted_churn": 30, "lower_bound_activations": 140, "upper_bound_activations": 160, ...}, ...], "model_version": "...", "trained_at": "...", "cache_expires_at": "..."}`
      - 200 OK on success, 401/403 on auth failure, 400 on insufficient data, 500 on error
    - Optional query param: `force_refresh=true` to bypass cache and retrain

- [x] **Task 5: Scheduled job for daily model retraining** (AC: #5)
  - [x] Create `service_webapp/src/ops/jobs/forecast_retraining.py`:
    - Function `retrain_subscriber_growth_forecast() -> None`:
      - Run as background job via APScheduler or cron (existing pattern from other scheduled jobs)
      - Call forecast endpoint logic internally (or extract to shared service function)
      - Log: model version, MAPE, training duration
      - Alert if MAPE > 15% (send to LangFuse or logging)
    - [x] Schedule: daily at 2 AM (low-traffic period) via `@scheduler.scheduled_job('cron', hour=2, minute=0)`
    - [x] Ensure job has DB access and error handling (don't crash on failures)

- [x] **Task 6: Frontend forecast chart component** (AC: #2, #4)
  - [x] Create `frontend/src/components/ops/Forecasts.tsx` (extend from Story 7.2 if needed).
  - [x] Create `frontend/src/components/ops/SubscriberGrowthChart.tsx`:
    - Use Recharts for line chart (already a dependency from Story 3.2 usage rings)
    - Chart layout:
      - X-axis: dates (next 90 days)
      - Y-axis: subscriber count
      - Line 1: predicted activations (solid line, blue)
      - Line 2: predicted churn (solid line, red)
      - Shaded area: confidence interval (activations) using AreaChart with low opacity
      - Shaded area: confidence interval (churn) using AreaChart with low opacity
    - Tooltip: show exact values on hover
    - Legend: activations vs churn
    - Responsive: full width of container
  - [x] Use React Query hook `useSubscriberGrowthForecast()`:
    - Call GET /api/v1/ops/forecasts/subscriber-growth
    - Refetch on mount (no auto-refresh, forecasts are cached daily)
    - Optional: "Refresh Forecast" button to call with `force_refresh=true`

- [x] **Task 7: Integration with ops dashboard** (AC: #4)
  - [x] Add "Subscriber Growth Forecast" tab to `frontend/src/pages/ops/Dashboard.tsx` (alongside Plan Stock and Order Fulfilment from Story 7.2).
  - [x] Tab content: render `SubscriberGrowthChart.tsx`
  - [x] Tab navigation: switch between "Plan Stock", "Order Fulfilment", "Forecasts"
  - [x] Loading state: show spinner while forecast loads
  - [x] Error state: show error message + retry button

- [x] **Task 8: Unit and integration tests** (AC: #1–#7)
  - [x] Model tests in `service_webapp/tests/unit/test_subscriber_growth_model.py`:
    - Test model training on synthetic data
    - Test prediction returns correct shape and columns
    - Test confidence interval bounds: lower <= predicted <= upper
    - Test MAPE calculation: perfect predictions = 0%, noisy predictions > 0%
  - [x] API tests in `service_webapp/tests/api/test_ops.py`:
    - Test `GET /api/v1/ops/forecasts/subscriber-growth` with ops role: 200, returns expected schema
    - Test with subscriber role: 403 Forbidden
    - Test with insufficient data (< 90 days): 400 "Insufficient historical data"
    - Test cache hit: second call returns same data without retraining (check `trained_at` unchanged)
    - Test `force_refresh=true`: bypasses cache, retrains model
    - Mock `SubscriberGrowthForecaster` to test endpoint logic independently
  - [x] Frontend tests in `frontend/src/components/ops/__tests__/`:
    - Test `SubscriberGrowthChart` renders with mock data
    - Test chart displays lines and confidence intervals
    - Test React Query hook calls endpoint correctly
    - Test error state displays message

- [x] **Task 9: Performance and optimization** (AC: #1, #3, #5)
  - [x] Model training optimization:
    - Limit training data to 180 days (sufficient for daily patterns)
    - Use efficient scikit-learn model (GradientBoostingRegressor with n_estimators=100)
    - Cache trained model in memory (class variable) if multiple requests in same process
  - [x] Database: ensure `subscribers.created_at` index exists for historical query speed
  - [x] Forecast cache: 24-hour TTL balances freshness and performance
  - [x] Monitor: endpoint should return < 2s on cache hit, < 10s on cache miss (model training)

- [x] **Task 10: Error handling and edge cases** (AC: #1, #3)
  - [x] Insufficient data: if < 90 days historical, return 400 error with clear message
  - [x] Model training failure: fall back to simple linear extrapolation (trend-only) if GradientBoosting fails
  - [x] MAPE threshold violation: log warning, emit LangFuse span, but still return forecast (soft gate)
  - [x] Database errors: return 500 with error message
  - [x] Scheduled job failures: retry with exponential backoff, alert after 3 consecutive failures

## Dev Notes

### ML forecasting tech stack

Architecture specifies `scikit-learn` for MVP forecasting. Story 7.3 uses GradientBoostingRegressor (captures non-linear trends and seasonality) with LinearRegression fallback. Target State may upgrade to TimesFM/Chronos/Prophet/NeuralForecast — this story's `SubscriberGrowthForecaster` class is designed to be model-agnostic. [Source: architecture.md:108,135]

### Forecast quality target (NFR-14)

MAPE < 15% is enforced by:
1. Eval harness in Story 7.1 (hard gate before implementation)
2. Soft check in this story (log warning on violation)
3. Daily retraining job (alert if MAPE degrades)

This two-tier approach ensures quality at development time and monitors it in production. [Source: architecture.md:NFR-14]

### CQRS compliance (ARCH-4)

Forecast endpoint uses:
- SELECT queries via `ops_queries.py` for historical data and cached forecasts
- INSERT query via `ops_queries.py` for writing new forecasts (write side)

The `forecast_results` table is a write-optimized cache (append-mostly). Read path queries it for dashboard display. This aligns with ARCH-4's CQRS guidance. [Source: architecture.md:ARCH-4]

### Confidence intervals

95% confidence intervals computed via:
- **Method 1 (preferred):** Quantile Regression (train separate models at 2.5th, 50th, 97.5th percentiles)
- **Method 2 (fallback):** Bootstrap residuals (sample residuals, add to predictions, compute percentiles)

Method 1 is more accurate but slower. Method 2 is faster. Story 7.3 can use Method 2 initially and upgrade to Method 1 in future if accuracy insufficient.

### Churn definition

Story 7.3 uses a churn proxy: `subscribers.last_activity_at < NOW() - INTERVAL '90 days' AND status = 'ACTIVE'`. True churn tracking (FR-44 mentions "churn data") may not exist in MVP schema. If `subscribers` table lacks `last_activity_at`, use an alternative proxy:
- No CDR events in last 90 days (JOIN with `cdr` events)
- Or use a simplified assumption: churn = 5% of activations (placeholder until real churn tracking exists)

This should be documented in dev notes as a known MVP limitation.

### Scheduled job pattern

APScheduler is already used for other jobs (e.g., notification triggers). Story 7.3 adds a daily job via `@scheduler.scheduled_job`. Ensure scheduler is initialized in `service_webapp/src/main.py` and survives across worker processes (if using uvicorn with multiple workers, run scheduler in main process only).

### Forecast cache TTL

24-hour TTL balances:
- **Freshness:** Daily retraining captures latest trends
- **Performance:** Cache hits avoid expensive model training
- **Cost:** Fewer LLM/API calls (if upgraded to external forecast service in future)

Admins can force refresh via `force_refresh=true` for on-demand updates.

### React Query for forecasts

Unlike plan stock (Story 7.2), forecasts don't auto-refresh every 30s — they're cached daily. Use React Query's `staleTime: 24 * 60 * 60 * 1000` to avoid unnecessary refetchs. Add a "Refresh Forecast" button for manual refresh.

### Recharts confidence interval

Use Recharts `<AreaChart>` with two series:
1. Lower bound line (lighter opacity)
2. Upper bound area (fills between line and upper bound)
3. Main prediction line (solid, darker)

This creates a shaded band effect. Reference Story 3.2's usage rings for Recharts patterns.

### Error handling hierarchy

1. **Insufficient data (< 90 days):** 400 error — clear message to ops team
2. **Model training failure:** Fall back to linear extrapolation — degrade gracefully
3. **MAPE > 15%:** Log warning, emit LangFuse span, still return forecast — soft gate
4. **Database error:** 500 error — retryable transient failure
5. **Scheduled job failure:** Retry with backoff, alert after 3 failures — ops team intervention

This ensures robustness in production while alerting on quality issues.

### Project Structure Notes

- New backend files: `service_webapp/src/ops/forecasting/subscriber_growth_model.py`, `service_webapp/src/ops/jobs/forecast_retraining.py`
- Modified backend files: `service_webapp/src/db/queries/ops_queries.py` (add forecast queries), `service_webapp/src/api/v1/ops.py` (add forecast endpoint)
- Migration: `V__forecast_cache.sql`
- New frontend files: `frontend/src/components/ops/SubscriberGrowthChart.tsx` (extend `Forecasts.tsx` from Story 7.2)
- Modified frontend files: `frontend/src/pages/ops/Dashboard.tsx` (add Forecast tab)
- No changes to: cdr-pipeline, auth service, existing subscriber components

### References

- [Source: epics.md §1.10.3 — Story 7.3 acceptance criteria]
- [Source: architecture.md:ARCH-4 — CQRS: read model via SELECT-only queries]
- [Source: architecture.md:103 — Auth: JWT with role claim]
- [Source: architecture.md:108 — ML Forecasting: scikit-learn (MVP)]
- [Source: architecture.md:FR-44 — Subscriber Growth Forecast]
- [Source: architecture.md:NFR-14 — MAPE < 15% for forecasting]
- [Source: docs/bmad_output/implementation-artifacts/7-1-eval-harness-ml-forecast-upsell-quality.md — eval harness patterns]
- [Source: docs/bmad_output/implementation-artifacts/7-2-plan-stock-dashboard-order-fulfilment-view.md — ops dashboard patterns]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- V11 migration creates a shared `forecast_results` table (not `ops_forecast_results`); Story 7.4's V12 depends on this and creates it only if V11 has not run. Subscriber-growth-specific columns added via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in the same migration.
- Churn is a CDR-based proxy (`DATE(MAX(billing_cdr_events.start_time)) + 90`) as `identity_subscribers` has no `last_activity_at` column. Documented as MVP limitation in the model docstring.
- `db.connection()` async context manager was missing from `Psycopg3AsyncAdapter` and `DatabaseProtocol`; added as part of this story (non-transactional pooled read).
- Confidence intervals use bootstrap residuals (Method 2); lower/upper bounds are clamped to `[lower, point, upper]` ordering.
- APScheduler job registered at 02:00 UTC; plan-demand job (Story 7.4) at 03:00 UTC to stagger DB load. Both registered in `forecast_retraining.py` and started in `main.py`.
- In-process `_TRAINED_CACHE` keyed by `(row_count, min_date, max_date)` signature provides secondary optimisation on top of the DB forecast cache.
- All 33 Story 7.3 tests pass (`tests/unit/test_subscriber_growth_model.py` × 13, `tests/api/test_ops.py` × 6 new + pre-existing passing). Ruff lint clean.

### File List

**New backend:**
- `service_webapp/db/migrations/V11__subscriber_growth_forecast.sql`
- `service_webapp/src/ops/forecasting/subscriber_growth_model.py`
- `service_webapp/tests/unit/test_subscriber_growth_model.py`

**Modified backend:**
- `service_webapp/src/adapters/postgres.py` — added `connection()` async context manager
- `service_webapp/src/core/protocols/db.py` — added `connection()` to `DatabaseProtocol`
- `service_webapp/src/db/ops/queries.py` — added `get_historical_activations_churn`, `get_cached_subscriber_growth_forecast`, `save_subscriber_growth_forecast`
- `service_webapp/src/routers/ops.py` — added `GET /forecasts/subscriber-growth` endpoint
- `service_webapp/src/ops/jobs/forecast_retraining.py` — added `retrain_subscriber_growth_forecast`, `register_subscriber_growth_job`
- `service_webapp/src/main.py` — registered `forecast_retraining_scheduler`
- `service_webapp/tests/api/test_ops.py` — added 6 subscriber-growth endpoint tests

**New frontend:**
- `frontend/src/portals/ops/SubscriberGrowthChart.tsx`
- `frontend/src/portals/ops/SubscriberGrowthForecast.tsx`
- `frontend/src/portals/ops/SubscriberGrowthChart.test.tsx`
- `frontend/src/portals/ops/SubscriberGrowthForecast.test.tsx`

**Modified frontend:**
- `frontend/src/portals/ops/hooks.ts` — added `SubscriberGrowthForecastData` types and `useSubscriberGrowthForecast` hook
- `frontend/src/portals/ops/Forecasts.tsx` — filled Subscriber Growth tab placeholder
- `frontend/src/portals/ops/Dashboard.test.tsx` — updated mocks
