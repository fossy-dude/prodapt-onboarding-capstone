---
baseline_commit: dd7e3df
---

# Story 7.4: Plan Demand Forecast (30–90 Day)

Status: ready-for-dev

## Story

As a **marketing team member**,
I want a 30 to 90-day demand forecast per plan so I can identify which plans to promote,
so that marketing spend targets high-growth segments.

## Acceptance Criteria

1. **Given** GET /api/v1/ops/forecasts/plan-demand is called, **When** the response is returned, **Then** it returns per-plan projections: plan_id, plan_name, predicted_uptake_30d, predicted_uptake_60d, predicted_uptake_90d. [Source: epics.md:2034; FR-45]

2. **And** predictions are computed using a per-plan scikit-learn model trained on the last 90 days of recharge events. [Source: epics.md:2036]

3. **And** the Forecasts.tsx page has a "Plan Demand" tab showing a sortable table of per-plan predictions with a sparkline trend chart per row. [Source: epics.md:2038]

4. **And** the forecast endpoint uses queries.py (SELECT only for reading cached results, INSERT for writing new forecasts) per CQRS rules. [Source: architecture.md:ARCH-4]

5. **And** role-based access control restricts the endpoint to users with role claim = 'ops' or 'marketing' in JWT (marketing team needs access). [Source: architecture.md:103; JWT role-based auth]

6. **And** the model is retrained daily via a scheduled job; results are cached in Postgres (forecast_results table, extended from Story 7.3). [Source: epics.md Story 7.3 pattern]

## Tasks / Subtasks

- [ ] **Task 1: Extend database schema for plan demand forecast** (AC: #1, #4, #6)
  - [ ] Create Flyway migration `V__plan_demand_forecast.sql`:
    - Extend `forecast_results` table (from Story 7.3) to support plan-level forecasts:
      - Add column `plan_id` UUID (nullable, NULL for subscriber-level forecasts like Story 7.3)
      - Add column `predicted_uptake_30d` INTEGER (nullable)
      - Add column `predicted_uptake_60d` INTEGER (nullable)
      - Add column `predicted_uptake_90d` INTEGER (nullable)
      - Add column `uptake_trend_90d` JSONB (array of 90 daily values for sparkline chart)
    - Update unique constraint to include plan_id: `UNIQUE (forecast_type, forecast_date, plan_id)`
    - Add index: `(forecast_type, plan_id, valid_until)` for efficient plan queries
  - [ ] Run migration via `just migrate`

- [ ] **Task 2: ML plan demand forecast model** (AC: #1, #2)
  - [ ] Create `service_webapp/src/ops/forecasting/plan_demand_model.py`.
  - [ ] Class `PlanDemandForecaster`:
    - `__init__(self, model_type: str = "gradient_boosting")`: initialize scikit-learn model (per-plan model)
    - `train_per_plan(self, plan_id: str, historical_recharges: pd.DataFrame) -> None`:
      - Input DataFrame columns: `date, plan_id, recharge_count, recharge_amount_paise`
      - Filter by `plan_id` to get plan-specific recharge history
      - Feature engineering: extract day_of_week, day_of_month, week_of_year, lag features (7-day moving average)
      - Train model for this plan: predict recharge count (uptake) based on time features
    - `predict(self, plan_id: str, horizon_days: int = 90) -> dict`:
      - Generate future dates from last historical date + horizon_days
      - Return dict:
        ```python
        {
          "plan_id": str,
          "predicted_uptake_30d": int,  # sum of first 30 days
          "predicted_uptake_60d": int,  # sum of first 60 days
          "predicted_uptake_90d": int,  # sum of first 90 days
          "uptake_trend_90d": list[int]  # daily predictions for sparkline
        }
        ```
    - `evaluate(self, plan_id: str, actual_data: pd.DataFrame) -> dict`:
      - Compute MAPE on holdout set (last 30 days) for this plan
      - Return: `{"mape": float, "passed_mape_threshold": bool}`
  - [ ] `train_all_plans(self, all_plan_data: dict[str, pd.DataFrame]) -> dict[str, Any]`:
    - Train a separate model for each plan (plans have different demand patterns)
    - Return dict of `plan_id -> model_metrics`
    - Skip plans with insufficient history (< 30 data points) — mark with predicted_uptake = 0

- [ ] **Task 3: Database queries for plan demand forecast** (AC: #1, #2, #4)
  - [ ] Add to `service_webapp/src/db/queries/ops_queries.py`:
    - Function `get_historical_plan_recharges(db_conn, days_back: int = 90) -> list[dict]`:
      - Query: `SELECT plan_id, DATE(recharged_at) as date, COUNT(*) as recharge_count, SUM(amount_paise) as recharge_amount_paise FROM billing_audit_log WHERE event_type = 'RECHARGE' AND recharged_at >= NOW() - INTERVAL ':days_back days' GROUP BY plan_id, DATE(recharged_at) ORDER BY plan_id, date`
      - Use `billing_audit_log` table ( Story 2.3 ) for recharge events
      - Return: list of `{"plan_id": uuid, "date": date, "recharge_count": int, "recharge_amount_paise": int}`
    - Function `get_cached_plan_forecast(db_conn, forecast_type: str = "plan_demand") -> list[dict]`:
      - Query: `SELECT * FROM forecast_results WHERE forecast_type = :forecast_type AND plan_id IS NOT NULL AND valid_until > NOW() ORDER BY plan_id`
      - Return list of forecast rows with plan_id
    - Function `save_plan_forecast_results(db_conn, forecasts: list[dict], model_version: str, valid_hours: int = 24) -> None`:
      - Delete old cache: `DELETE FROM forecast_results WHERE forecast_type = 'plan_demand'`
      - Insert new rows: batch INSERT from list of forecast dicts
      - Set `valid_until = NOW() + INTERVAL ':valid_hours hours'`

- [ ] **Task 4: FastAPI endpoint for plan demand forecast** (AC: #1, #2, #4, #5)
  - [ ] Add to `service_webapp/src/api/v1/ops.py`:
    - Endpoint `GET /api/v1/ops/forecasts/plan-demand`:
      - Auth dependency: `require_role(["ops", "marketing"])` (both roles can access)
      - Logic:
        1. Check cached forecast via `get_cached_plan_forecast(db_conn)`
        2. If cache valid, return cached data immediately
        3. If cache expired/missing:
           - Fetch historical data via `get_historical_plan_recharges(db_conn, days_back=90)`
           - Group by plan_id: `all_plan_data = {plan_id: DataFrame, ...}`
           - Train models via `PlanDemandForecaster.train_all_plans(all_plan_data)`
           - Generate forecasts for all plans via `predict(plan_id, horizon_days=90)` for each
           - Cache results via `save_plan_forecast_results(db_conn, forecasts, model_version)`
           - Return forecast data
      - Return JSON: `{"forecasts": [{"plan_id": "...", "plan_name": "...", "predicted_uptake_30d": 150, "predicted_uptake_60d": 320, "predicted_uptake_90d": 500, "uptake_trend_90d": [5, 6, 4, 7, ...]}, ...], "model_version": "...", "trained_at": "...", "cache_expires_at": "..."}`
      - Join with `plans` table to get `plan_name` for each forecast
      - 200 OK on success, 401/403 on auth failure, 500 on error
    - Optional query param: `force_refresh=true` to bypass cache

- [ ] **Task 5: Scheduled job for daily plan demand retraining** (AC: #6)
  - [ ] Add to `service_webapp/src/ops/jobs/forecast_retraining.py`:
    - Function `retrain_plan_demand_forecast() -> None`:
      - Run as background job via APScheduler (same scheduler as Story 7.3)
      - Call plan demand forecast endpoint logic internally
      - Log: per-plan model metrics, training duration
      - Alert if any plan's MAPE > 15%
    - [ ] Schedule: daily at 3 AM (1 hour after subscriber growth forecast to spread load) via `@scheduler.scheduled_job('cron', hour=3, minute=0)`
    - [ ] Ensure job has DB access and error handling

- [ ] **Task 6: Frontend plan demand forecast table** (AC: #1, #3)
  - [ ] Extend `frontend/src/components/ops/Forecasts.tsx` from Story 7.3:
    - Add "Plan Demand" tab alongside "Subscriber Growth" tab
  - [ ] Create `frontend/src/components/ops/PlanDemandTable.tsx`:
    - Table structure:
      - Columns: Plan Name, Predicted Uptake (30d), Predicted Uptake (60d), Predicted Uptake (90d), Trend (sparkline)
      - Sortable by plan name and uptake columns
      - Default sort: predicted_uptake_90d descending (highest growth plans first)
    - Sparkline chart per row:
      - Use Recharts `<AreaChart>` or `<LineChart>` with minimal height (60px)
      - Show `uptake_trend_90d` array as mini trend line
      - Color: green for upward trend, red for flat/downward
    - Use TanStack Table (React Table v8) for sorting
    - Responsive: table stacks on mobile

- [ ] **Task 7: React Query hook for plan demand** (AC: #1, #3)
  - [ ] Create `frontend/src/hooks/usePlanDemandForecast.ts` (or add to component file):
    - `usePlanDemandForecast()` hook:
      - Call GET /api/v1/ops/forecasts/plan-demand
      - Refetch on mount (no auto-refresh, forecasts are cached daily)
      - Optional: "Refresh Forecast" button to call with `force_refresh=true`
      - Transform API response to table-friendly format
    - Error handling: show toast on query failure

- [ ] **Task 8: Integration with ops dashboard** (AC: #3)
  - [ ] Add "Plan Demand" tab to `frontend/src/pages/ops/Dashboard.tsx` Forecast section.
  - [ ] Tab content: render `PlanDemandTable.tsx`
  - [ ] Tab navigation: switch between "Subscriber Growth" and "Plan Demand"
  - [ ] Loading state: show spinner while forecast loads
  - [ ] Error state: show error message + retry button

- [ ] **Task 9: Unit and integration tests** (AC: #1–#6)
  - [ ] Model tests in `service_webapp/tests/unit/test_plan_demand_model.py`:
    - Test per-plan model training on synthetic data
    - Test prediction returns correct shape and columns
    - Test uptake aggregation: 30d/60d/90d sums match daily trend
    - Test MAPE calculation per plan
    - Test plans with insufficient history are skipped gracefully
  - [ ] API tests in `service_webapp/tests/api/test_ops.py`:
    - Test `GET /api/v1/ops/forecasts/plan-demand` with ops role: 200, returns expected schema
    - Test with marketing role: 200 (marketing has access)
    - Test with subscriber role: 403 Forbidden
    - Test cache hit: second call returns same data without retraining
    - Test `force_refresh=true`: bypasses cache, retrains all plan models
    - Mock `PlanDemandForecaster` to test endpoint logic independently
  - [ ] Frontend tests in `frontend/src/components/ops/__tests__/`:
    - Test `PlanDemandTable` renders with mock data
    - Test table sorts by columns correctly
    - Test sparkline charts display per row
    - Test React Query hook calls endpoint correctly

- [ ] **Task 10: Performance and optimization** (AC: #1, #2, #5)
  - [ ] Model training optimization:
    - Limit training data to 90 days per plan (sufficient for demand patterns)
    - Train plans in parallel (use `concurrent.futures.ThreadPoolExecutor` or async)
    - Skip plans with < 30 data points (insufficient history)
  - [ ] Database: ensure `billing_audit_log.recharged_at` and `billing_audit_log.event_type` indexes exist
  - [ ] Forecast cache: 24-hour TTL (same as Story 7.3)
  - [ ] Monitor: endpoint should return < 2s on cache hit, < 30s on cache miss (training all plans)

- [ ] **Task 11: Error handling and edge cases** (AC: #1, #2)
  - [ ] No recharge history for a plan: set predicted_uptake to 0, include in response with zero values
  - [ ] Insufficient data (< 30 days): skip plan from forecast, log warning
  - [ ] Model training failure for one plan: continue with other plans, log failed plan_id
  - [ ] Database errors: return 500 with error message
  - [ ] Scheduled job failures: retry with exponential backoff, alert per-plan failures

## Dev Notes

### Per-plan forecasting

Story 7.4 trains a separate scikit-learn model for each plan (not one global model). Plans have different demand patterns:
- Budget plans: steady, predictable uptake
- High-value plans: spiky, event-driven uptake
- Data-heavy plans: seasonal patterns

Per-plan models capture these nuances. Trade-off: more training time (1000 plans in Story 2.6 synthetic dataset) vs. better accuracy. Parallel training mitigates time cost. [Source: architecture.md:108; FR-45]

### ML forecasting tech stack

Uses `scikit-learn` (same as Story 7.3). GradientBoostingRegressor with plan-specific features (day_of_week, lag features). Target State may upgrade to TimesFM/Chronos — the `PlanDemandForecaster` class is model-agnostic. [Source: architecture.md:108,135]

### Data source: billing_audit_log

Plan demand forecasts use `billing_audit_log` table (Story 2.3) for recharge events. Filter by `event_type = 'RECHARGE'` and extract `plan_id` from the audit log. If plan_id is not in billing_audit_log, use `subscriber_orders.plan_id` JOIN with `billing_audit_log.subscriber_id` as fallback.

### Uptake aggregation

`predicted_uptake_30d/60d/90d` are **sums** of daily predictions, not point forecasts. Example:
- Daily predictions for Plan A: [5, 6, 4, 7, 5, ...] (90 values)
- predicted_uptake_30d = sum(first 30 values) = 150
- predicted_uptake_60d = sum(first 60 values) = 320
- predicted_uptake_90d = sum(all 90 values) = 500

This aligns with marketing's use case: "how many total recharges expected in 30/60/90 days?" (FR-45).

### Sparkline trend

`uptake_trend_90d` is the raw daily prediction array (90 integers). Frontend renders this as a mini sparkline chart using Recharts `<AreaChart>` with minimal height. Sparkline shows the **shape** of demand (upward, flat, seasonal) — marketing uses this to plan campaign timing.

### CQRS compliance (ARCH-4)

Forecast endpoint uses:
- SELECT queries via `ops_queries.py` for historical recharge data and cached forecasts
- INSERT query via `ops_queries.py` for writing new forecasts (write side)

Same pattern as Story 7.3. `forecast_results` table is a write-optimized cache, read for dashboard display. [Source: architecture.md:ARCH-4]

### Role-based access control

Marketing team needs access to plan demand forecasts (they're the primary consumers). Story 7.4 extends the auth dependency to accept both `ops` and `marketing` roles: `require_role(["ops", "marketing"])`. This aligns with FR-45's user persona ("marketing team member"). [Source: architecture.md:103]

### Scheduled job pattern

Same as Story 7.3: daily job via APScheduler. Run at 3 AM (1 hour after subscriber growth forecast) to spread load. Both jobs can run in parallel — they use different data sources and tables.

### Forecast cache TTL

24-hour TTL (same as Story 7.3). Plan demand patterns change slower than subscriber growth (recharge behavior is more stable), so 24-hour cache is appropriate. Marketing can force refresh via `force_refresh=true` if needed (e.g., after a promotion campaign).

### Parallel training for 1000 plans

Story 2.6 synthetic dataset has 1000 plans. Training 1000 GradientBoostingRegressor models sequentially would be slow (~30 minutes). Story 7.4 uses `concurrent.futures.ThreadPoolExecutor` to train plans in parallel:
```python
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(train_plan, plan_id, data): plan_id for plan_id, data in all_plan_data.items()}
    for future in as_completed(futures):
        plan_id = futures[future]
        model_metrics[plan_id] = future.result()
```

This reduces training time to ~5-10 minutes (acceptable for daily job).

### Sparkline rendering

Recharts `<AreaChart>` with minimal height (60px) and no axes/labels creates a sparkline effect. Use `uptake_trend_90d` array as data. Color coding:
- Green: upward trend (last_7d_avg > first_7d_avg)
- Red: flat/downward trend

Marketing uses sparklines to spot growth patterns quickly.

### Error handling per plan

If one plan's model fails (insufficient data, training error), Story 7.4 continues with other plans rather than failing the entire forecast. Log the failed plan_id and emit a LangFuse span. Marketing sees 0 uptake for failed plans (graceful degradation).

### Project Structure Notes

- New backend files: `service_webapp/src/ops/forecasting/plan_demand_model.py`
- Modified backend files: `service_webapp/src/db/queries/ops_queries.py` (add plan demand queries), `service_webapp/src/api/v1/ops.py` (add plan demand endpoint), `service_webapp/src/ops/jobs/forecast_retraining.py` (add plan demand job)
- Migration: `V__plan_demand_forecast.sql` (extends forecast_results table)
- New frontend files: `frontend/src/components/ops/PlanDemandTable.tsx` (extend `Forecasts.tsx` from Story 7.3)
- Modified frontend files: `frontend/src/pages/ops/Dashboard.tsx` (add Plan Demand tab)
- No changes to: cdr-pipeline, auth service, existing subscriber components

### References

- [Source: epics.md §1.10.4 — Story 7.4 acceptance criteria]
- [Source: architecture.md:ARCH-4 — CQRS: read model via SELECT-only queries]
- [Source: architecture.md:103 — Auth: JWT with role claim]
- [Source: architecture.md:108 — ML Forecasting: scikit-learn (MVP)]
- [Source: architecture.md:FR-45 — Plan Popularity Forecast]
- [Source: docs/bmad_output/implementation-artifacts/7-1-eval-harness-ml-forecast-upsell-quality.md — eval harness patterns]
- [Source: docs/bmad_output/implementation-artifacts/7-2-plan-stock-dashboard-order-fulfilment-view.md — ops dashboard patterns]
- [Source: docs/bmad_output/implementation-artifacts/7-3-subscriber-growth-forecast-ml-3-month.md — forecast cache pattern]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
