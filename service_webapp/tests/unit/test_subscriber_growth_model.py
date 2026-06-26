"""Unit tests for the subscriber growth forecaster (Story 7.3 Task 8).

Covers the MAPE helper, train/predict shape + confidence-interval ordering, the
minimum-history guard, model fallback, and the ``build_forecast_payload`` orchestration
shape consumed by the API endpoint and the retraining job.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ops.forecasting import subscriber_growth_model as sgm
from ops.forecasting.subscriber_growth_model import (
    SubscriberGrowthForecaster,
    _mape,
    build_forecast_payload,
)

_FORECAST_COLUMNS = {
    "date",
    "predicted_activations",
    "predicted_churn",
    "lower_bound_activations",
    "upper_bound_activations",
    "lower_bound_churn",
    "upper_bound_churn",
}


def _make_history(n_days: int = 180, seed: int = 42) -> list[dict]:
    """Synthetic daily activations + churn with trend and weekly seasonality."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n_days, freq="D")
    t = np.arange(n_days)
    activations = np.clip(100 + 0.5 * t + 20 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 5, n_days), 0, None).astype(
        int
    )
    churn = np.clip(0.05 * activations + rng.normal(0, 2, n_days), 0, None).astype(int)
    return [
        {"date": d.date().isoformat(), "activations": int(a), "churn": int(c)}
        for d, a, c in zip(dates, activations, churn, strict=True)
    ]


@pytest.fixture(autouse=True)
def _clear_model_cache() -> None:
    """Reset the in-process forecaster cache between tests for isolation."""
    sgm._TRAINED_CACHE.clear()


# ── MAPE helper ───────────────────────────────────────────────────────────────


def test_mape_zero_for_perfect_predictions() -> None:
    assert _mape(np.array([100.0, 200.0, 300.0]), np.array([100.0, 200.0, 300.0])) == 0.0


def test_mape_positive_for_error() -> None:
    # |100-150|/100 = 0.5 -> 50%
    assert _mape(np.array([100.0]), np.array([150.0])) == 50.0


def test_mape_ignores_zero_actuals() -> None:
    # Only the 100 point counts: |100-150|/100 = 50%
    assert _mape(np.array([0.0, 100.0]), np.array([50.0, 150.0])) == 50.0


def test_mape_all_zero_actuals_is_zero() -> None:
    assert _mape(np.array([0.0, 0.0]), np.array([5.0, 9.0])) == 0.0


# ── Train / predict ───────────────────────────────────────────────────────────


def test_train_then_predict_returns_correct_shape_and_columns() -> None:
    forecaster = SubscriberGrowthForecaster()
    forecaster.train(pd.DataFrame(_make_history(180)))

    forecast = forecaster.predict(horizon_days=90)

    assert len(forecast) == 90
    assert set(forecast.columns) == _FORECAST_COLUMNS


def test_confidence_interval_bounds_enclose_predictions() -> None:
    forecaster = SubscriberGrowthForecaster()
    forecaster.train(pd.DataFrame(_make_history(180)))

    forecast = forecaster.predict(horizon_days=90)

    for col_pred, col_low, col_high in (
        ("predicted_activations", "lower_bound_activations", "upper_bound_activations"),
        ("predicted_churn", "lower_bound_churn", "upper_bound_churn"),
    ):
        assert (forecast[col_low] <= forecast[col_pred]).all()
        assert (forecast[col_pred] <= forecast[col_high]).all()
    # Counts are non-negative integers.
    for col in _FORECAST_COLUMNS - {"date"}:
        assert (forecast[col] >= 0).all()


def test_predict_before_train_raises() -> None:
    forecaster = SubscriberGrowthForecaster()
    with pytest.raises(RuntimeError):
        forecaster.predict(90)


def test_train_requires_minimum_history() -> None:
    forecaster = SubscriberGrowthForecaster()
    with pytest.raises(ValueError, match="daily points"):
        forecaster.train(pd.DataFrame(_make_history(20)))


def test_linear_model_type_trains_and_predicts() -> None:
    forecaster = SubscriberGrowthForecaster(model_type="linear")
    forecaster.train(pd.DataFrame(_make_history(180)))
    forecast = forecaster.predict(horizon_days=30)
    assert forecaster.effective_model_type == "linear"
    assert len(forecast) == 30


def test_unknown_model_type_rejected() -> None:
    with pytest.raises(ValueError, match="model_type"):
        SubscriberGrowthForecaster(model_type="unknown")


def test_evaluate_returns_expected_keys() -> None:
    history = _make_history(180)
    forecaster = SubscriberGrowthForecaster()
    forecaster.train(pd.DataFrame(history))

    metrics = forecaster.evaluate(pd.DataFrame(history[-30:]))

    assert set(metrics) == {"mape_activations", "mape_churn", "passed_mape_threshold"}
    assert metrics["mape_activations"] >= 0.0
    assert metrics["mape_churn"] >= 0.0
    assert isinstance(metrics["passed_mape_threshold"], bool)


# ── build_forecast_payload orchestration ─────────────────────────────────────


def test_build_forecast_payload_structure() -> None:
    payload = build_forecast_payload(_make_history(180), horizon_days=90, holdout_days=30)

    assert payload["forecast_type"] == "subscriber_growth"
    assert payload["model_version"].endswith("_v1")
    assert payload["horizon_days"] == 90
    assert "trained_at" in payload

    metrics = payload["metrics"]
    assert {"mape_activations", "mape_churn", "passed_mape_threshold", "holdout_days"} <= set(metrics)
    assert metrics["holdout_days"] == 30

    forecasts = payload["forecasts"]
    assert len(forecasts) == 90
    point = forecasts[0]
    assert set(point) == _FORECAST_COLUMNS
    # Dates are ISO YYYY-MM-DD strings.
    assert len(point["date"]) == 10
    # Bound ordering preserved through serialisation.
    assert point["lower_bound_activations"] <= point["predicted_activations"] <= point["upper_bound_activations"]
    assert point["lower_bound_churn"] <= point["predicted_churn"] <= point["upper_bound_churn"]


def test_build_forecast_payload_rejects_empty_history() -> None:
    with pytest.raises(ValueError, match="date, activations, churn"):
        build_forecast_payload([])
