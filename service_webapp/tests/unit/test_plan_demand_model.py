"""Unit tests for PlanDemandForecaster (Story 7.4 Task 9)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ops.forecasting.plan_demand_model import _MIN_POINTS, PlanDemandForecaster


def _daily_series(n: int, base: float = 5.0, noise: float = 1.0) -> pd.Series:
    """Synthetic daily recharge count series of length *n*."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    values = np.maximum(0, base + rng.normal(0, noise, n)).astype(int)
    return pd.Series(values, index=dates)


class TestForecastPlan:
    def test_returns_correct_keys(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        result = forecaster.forecast_plan("plan-1", series)

        assert set(result.keys()) == {
            "plan_id",
            "predicted_uptake_30d",
            "predicted_uptake_60d",
            "predicted_uptake_90d",
            "uptake_trend_90d",
        }

    def test_trend_length_is_90(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        result = forecaster.forecast_plan("plan-1", series)

        assert len(result["uptake_trend_90d"]) == 90

    def test_uptake_aggregations_match_trend_slices(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        result = forecaster.forecast_plan("plan-1", series)
        trend = result["uptake_trend_90d"]

        assert result["predicted_uptake_30d"] == sum(trend[:30])
        assert result["predicted_uptake_60d"] == sum(trend[:60])
        assert result["predicted_uptake_90d"] == sum(trend[:90])

    def test_all_predictions_non_negative(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        result = forecaster.forecast_plan("plan-1", series)

        assert result["predicted_uptake_30d"] >= 0
        assert result["predicted_uptake_60d"] >= 0
        assert result["predicted_uptake_90d"] >= 0
        assert all(v >= 0 for v in result["uptake_trend_90d"])

    def test_insufficient_history_returns_zeros(self):
        forecaster = PlanDemandForecaster()
        short_series = _daily_series(_MIN_POINTS - 1)
        result = forecaster.forecast_plan("plan-x", short_series)

        assert result["predicted_uptake_30d"] == 0
        assert result["predicted_uptake_90d"] == 0
        assert result["uptake_trend_90d"] == [0] * 90

    def test_moving_average_method_works(self):
        forecaster = PlanDemandForecaster(method="moving_average")
        series = _daily_series(60)
        result = forecaster.forecast_plan("plan-1", series)

        assert len(result["uptake_trend_90d"]) == 90
        assert result["predicted_uptake_90d"] >= 0

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="Unknown method"):
            PlanDemandForecaster(method="xgboost")

    def test_plan_id_passed_through(self):
        forecaster = PlanDemandForecaster()
        result = forecaster.forecast_plan("my-plan-uuid", _daily_series(60))
        assert result["plan_id"] == "my-plan-uuid"

    def test_gaps_in_series_filled(self):
        forecaster = PlanDemandForecaster()
        dates = pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-10"])
        series = pd.Series([10, 8, 12], index=dates)
        result = forecaster.forecast_plan("plan-gaps", series)

        assert len(result["uptake_trend_90d"]) == 90


class TestEvaluate:
    def test_returns_mape_and_threshold_flag(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        metrics = forecaster.evaluate(series)

        assert "mape" in metrics
        assert "passed_mape_threshold" in metrics
        assert isinstance(metrics["mape"], float)
        assert isinstance(metrics["passed_mape_threshold"], bool)

    def test_too_short_series_passes_by_default(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(_MIN_POINTS)
        metrics = forecaster.evaluate(series)

        assert metrics["passed_mape_threshold"] is True

    def test_mape_non_negative(self):
        forecaster = PlanDemandForecaster()
        series = _daily_series(60)
        metrics = forecaster.evaluate(series)

        assert metrics["mape"] >= 0.0


class TestForecastAllPlans:
    def test_returns_dict_keyed_by_plan_id(self):
        forecaster = PlanDemandForecaster()
        data = {
            "plan-a": _daily_series(60),
            "plan-b": _daily_series(60, base=8.0),
        }
        results = forecaster.forecast_all_plans(data)

        assert set(results.keys()) == {"plan-a", "plan-b"}

    def test_short_plan_included_with_zeros(self):
        forecaster = PlanDemandForecaster()
        data = {
            "plan-ok": _daily_series(60),
            "plan-short": _daily_series(5),
        }
        results = forecaster.forecast_all_plans(data)

        assert results["plan-short"]["predicted_uptake_90d"] == 0

    def test_exception_in_one_plan_does_not_break_others(self):
        forecaster = PlanDemandForecaster()

        empty_series = pd.Series([], dtype=float)
        data = {
            "plan-empty": empty_series,
            "plan-good": _daily_series(60),
        }
        results = forecaster.forecast_all_plans(data)

        assert "plan-good" in results
        assert results["plan-good"]["predicted_uptake_90d"] >= 0

    def test_empty_input_returns_empty_dict(self):
        forecaster = PlanDemandForecaster()
        results = forecaster.forecast_all_plans({})
        assert results == {}
