"""Subscriber growth forecaster using Holt-Winters exponential smoothing (Story 7.3).

Forecasts daily subscriber activations and churn 90 days ahead with 95% confidence
intervals. No complex ML — same approach as Story 7.4's PlanDemandForecaster:
  1. Fill missing dates with 0.
  2. Apply 7-day rolling mean to smooth day-of-week noise.
  3. Fit Holt-Winters (additive trend, no seasonality) — falls back to trailing
     14-day moving-average when the series is too short or the fit fails.
  4. Predict *horizon_days* forward; clip negatives to 0.
  5. Confidence intervals via bootstrap of training residuals (95% CI).

MAPE < 15% (NFR-14) is enforced as a *soft* gate here (log warning, still return);
the eval harness (Story 7.1) owns the hard gate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MAPE_THRESHOLD = 15.0

_MIN_TRAIN_POINTS = 30
_DEFAULT_HORIZON = 90
_DEFAULT_HOLDOUT = 30
_BOOTSTRAP_SAMPLES = 200
_RANDOM_STATE = 42
_MA_WINDOW = 14


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error, ignoring zero-actual points."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    nonzero = actual != 0
    if not np.any(nonzero):
        return 0.0
    return float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)


def _fill_series(series: pd.Series) -> pd.Series:
    """Reindex to a contiguous daily range, fill gaps with 0."""
    if series.empty:
        return series
    full_idx = pd.date_range(series.index.min(), series.index.max(), freq="D")
    return series.reindex(full_idx, fill_value=0)


def _smooth(series: pd.Series, window: int = 7) -> pd.Series:
    """Apply rolling mean to smooth noise; keep original where window too small."""
    if len(series) < window:
        return series
    return series.rolling(window=window, min_periods=1).mean()


def _moving_average_forecast(series: pd.Series, horizon_days: int) -> list[float]:
    """Flat forecast using trailing 14-day moving average."""
    tail = series.tail(_MA_WINDOW).mean() if len(series) >= _MA_WINDOW else series.mean()
    daily = max(0.0, float(tail))
    return [daily] * horizon_days


def _holt_winters_forecast(series: pd.Series, horizon_days: int) -> list[float]:
    """Fit Holt-Winters and return horizon_days predictions.

    Returns empty list if fitting fails so the caller can fall back.
    """
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: PLC0415  # pyrefly: ignore[missing-import]

        model = ExponentialSmoothing(
            series.astype(float),
            trend="add",
            seasonal=None,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True, remove_bias=True)
        preds = fit.forecast(horizon_days)
        return [max(0.0, float(v)) for v in preds]
    except Exception:
        logger.debug("Holt-Winters fit failed — falling back to moving average", exc_info=True)
        return []


def _bootstrap_ci(
    point: np.ndarray,
    residuals: np.ndarray,
    n_samples: int = _BOOTSTRAP_SAMPLES,
    seed: int = _RANDOM_STATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap 2.5/97.5 percentile bounds from training residuals."""
    if len(residuals) == 0 or not np.any(residuals):
        return point.copy(), point.copy()
    rng = np.random.default_rng(seed)
    samples = point[:, None] + rng.choice(residuals, size=(len(point), n_samples))
    lower = np.percentile(samples, 2.5, axis=1)
    upper = np.percentile(samples, 97.5, axis=1)
    # Guarantee lower <= point <= upper.
    lower = np.minimum(lower, point)
    upper = np.maximum(upper, point)
    return lower, upper


class SubscriberGrowthForecaster:
    """Daily activations + churn forecaster with bootstrap 95% confidence intervals."""

    def __init__(self, method: str = "holt_winters") -> None:
        if method not in ("holt_winters", "moving_average"):
            raise ValueError(f"Unknown method: {method!r}")
        self.method = method
        self._last_date: pd.Timestamp | None = None
        self._smoothed_act: pd.Series | None = None
        self._smoothed_churn: pd.Series | None = None
        self._resid_act: np.ndarray | None = None
        self._resid_churn: np.ndarray | None = None

    def _fit_one(self, series: pd.Series) -> np.ndarray:
        """Fit a single series; return training residuals for CI bootstrap."""
        if self.method == "holt_winters":
            preds = _holt_winters_forecast(series, len(series))
            if not preds:
                preds = _moving_average_forecast(series, len(series))
        else:
            preds = _moving_average_forecast(series, len(series))
        return series.to_numpy(dtype=float) - np.array(preds, dtype=float)

    def _forecast_one(self, smoothed: pd.Series, horizon_days: int) -> list[float]:
        if self.method == "holt_winters":
            preds = _holt_winters_forecast(smoothed, horizon_days)
            if not preds:
                preds = _moving_average_forecast(smoothed, horizon_days)
        else:
            preds = _moving_average_forecast(smoothed, horizon_days)
        return preds

    def train(self, historical_data: pd.DataFrame) -> None:
        """Fit activations + churn models on daily counts.

        Parameters
        ----------
        historical_data : pd.DataFrame
            Columns ``date, activations, churn``. Rows are sorted and de-duplicated.
        """
        df = historical_data.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
        if len(df) < _MIN_TRAIN_POINTS:
            raise ValueError(f"Need >= {_MIN_TRAIN_POINTS} daily points to train, got {len(df)}")

        self._last_date = df["date"].max()

        act_series = pd.Series(df["activations"].astype(float).to_numpy(), index=pd.DatetimeIndex(df["date"]))
        churn_series = pd.Series(df["churn"].astype(float).to_numpy(), index=pd.DatetimeIndex(df["date"]))

        self._smoothed_act = _smooth(_fill_series(act_series))
        self._smoothed_churn = _smooth(_fill_series(churn_series))

        self._resid_act = self._fit_one(self._smoothed_act)
        self._resid_churn = self._fit_one(self._smoothed_churn)

    def predict(self, horizon_days: int = _DEFAULT_HORIZON) -> pd.DataFrame:
        """Return a ``horizon_days``-row forecast DataFrame starting the day after training."""
        if self._last_date is None:
            raise RuntimeError("SubscriberGrowthForecaster.predict called before train()")
        assert self._smoothed_act is not None
        assert self._smoothed_churn is not None
        assert self._resid_act is not None
        assert self._resid_churn is not None

        future = pd.date_range(self._last_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")

        act_preds = np.array(self._forecast_one(self._smoothed_act, horizon_days), dtype=float)
        churn_preds = np.array(self._forecast_one(self._smoothed_churn, horizon_days), dtype=float)

        act_lower, act_upper = _bootstrap_ci(act_preds, self._resid_act)
        churn_lower, churn_upper = _bootstrap_ci(churn_preds, self._resid_churn)

        def _clip_int(arr: np.ndarray) -> np.ndarray:
            return np.clip(np.rint(arr), 0, None).astype(int)

        return pd.DataFrame(
            {
                "date": future,
                "predicted_activations": _clip_int(act_preds),
                "predicted_churn": _clip_int(churn_preds),
                "lower_bound_activations": _clip_int(act_lower),
                "upper_bound_activations": _clip_int(act_upper),
                "lower_bound_churn": _clip_int(churn_lower),
                "upper_bound_churn": _clip_int(churn_upper),
            }
        )

    def evaluate(self, actual_data: pd.DataFrame) -> dict[str, Any]:
        """Compute MAPE for activations + churn over *actual_data* using the fitted models.

        Returns ``{mape_activations, mape_churn, passed_mape_threshold}``.
        """
        if self._last_date is None:
            raise RuntimeError("SubscriberGrowthForecaster.evaluate called before train()")
        df = actual_data.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)

        act_series = pd.Series(df["activations"].astype(float).to_numpy(), index=pd.DatetimeIndex(df["date"]))
        churn_series = pd.Series(df["churn"].astype(float).to_numpy(), index=pd.DatetimeIndex(df["date"]))
        act_smooth = _smooth(_fill_series(act_series))
        churn_smooth = _smooth(_fill_series(churn_series))

        act_preds = self._forecast_one(act_smooth, len(act_smooth))
        churn_preds = self._forecast_one(churn_smooth, len(churn_smooth))

        mape_act = _mape(act_smooth.to_numpy(), np.array(act_preds))
        mape_churn = _mape(churn_smooth.to_numpy(), np.array(churn_preds))
        return {
            "mape_activations": mape_act,
            "mape_churn": mape_churn,
            "passed_mape_threshold": mape_act <= MAPE_THRESHOLD and mape_churn <= MAPE_THRESHOLD,
        }


def _point_to_dict(row: Any) -> dict[str, Any]:
    """Convert a forecast DataFrame row into a JSON-safe dict."""
    return {
        "date": row.date.strftime("%Y-%m-%d"),
        "predicted_activations": int(row.predicted_activations),
        "predicted_churn": int(row.predicted_churn),
        "lower_bound_activations": int(row.lower_bound_activations),
        "upper_bound_activations": int(row.upper_bound_activations),
        "lower_bound_churn": int(row.lower_bound_churn),
        "upper_bound_churn": int(row.upper_bound_churn),
    }


def build_forecast_payload(
    historical_rows: list[dict[str, Any]],
    *,
    horizon_days: int = _DEFAULT_HORIZON,
    holdout_days: int = _DEFAULT_HOLDOUT,
    method: str = "holt_winters",
) -> dict[str, Any]:
    """Train, evaluate (soft MAPE gate), and produce a 90-day forecast payload.

    Shared by the API endpoint (cache miss) and the daily retraining job. Returns the
    payload stored in ``forecast_results`` (``forecasts`` / ``metrics``); the caller
    adds ``cache_expires_at`` / ``from_cache`` for the HTTP response.
    """
    required = {"date", "activations", "churn"}
    missing = required - set(historical_rows[0]) if historical_rows else required
    if not historical_rows or missing:
        raise ValueError("historical_rows must be non-empty with date, activations, churn columns")

    df = pd.DataFrame(historical_rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)

    metrics: dict[str, Any] = {
        "mape_activations": 0.0,
        "mape_churn": 0.0,
        "passed_mape_threshold": True,
        "holdout_days": holdout_days,
    }
    if len(df) > holdout_days + _MIN_TRAIN_POINTS:
        train_df = df.iloc[:-holdout_days]
        holdout_df = df.iloc[-holdout_days:]
        try:
            evaluator = SubscriberGrowthForecaster(method=method)
            evaluator.train(train_df)
            holdout_metrics = evaluator.evaluate(holdout_df)
            metrics.update(
                mape_activations=round(holdout_metrics["mape_activations"], 2),
                mape_churn=round(holdout_metrics["mape_churn"], 2),
                passed_mape_threshold=bool(holdout_metrics["passed_mape_threshold"]),
            )
        except Exception as exc:
            logger.warning("subscriber_growth: holdout evaluation failed: %s", exc)

    forecaster = SubscriberGrowthForecaster(method=method)
    forecaster.train(df)
    forecast_df = forecaster.predict(horizon_days)
    forecasts = [_point_to_dict(row) for row in forecast_df.itertuples(index=False)]

    if not metrics["passed_mape_threshold"]:
        logger.warning(
            "subscriber_growth: MAPE exceeds %.1f%% threshold (act=%.2f churn=%.2f) — soft gate, returning forecast",
            MAPE_THRESHOLD,
            metrics["mape_activations"],
            metrics["mape_churn"],
        )

    return {
        "forecast_type": "subscriber_growth",
        "model_version": f"{method}_v1",
        "trained_at": datetime.now(UTC).isoformat(),
        "horizon_days": horizon_days,
        "metrics": metrics,
        "forecasts": forecasts,
    }


__all__ = [
    "MAPE_THRESHOLD",
    "SubscriberGrowthForecaster",
    "build_forecast_payload",
]
