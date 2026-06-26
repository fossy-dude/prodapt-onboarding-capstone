"""Plan demand forecaster using Holt-Winters exponential smoothing (Story 7.4).

Per-plan time-series forecast of daily recharge counts.  No complex ML:
  1. Fill missing dates with 0.
  2. Apply 7-day rolling mean to smooth day-of-week noise.
  3. Fit Holt-Winters (additive trend, no seasonality) — falls back to trailing
     14-day moving-average when the series is too short or the fit fails.
  4. Predict *horizon_days* forward; clip negatives to 0.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MIN_POINTS = 14
_HOLDOUT_DAYS = 14
_MAPE_THRESHOLD = 25.0


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
    smoothed = series.rolling(window=window, min_periods=1).mean()
    return smoothed


def _moving_average_forecast(series: pd.Series, horizon_days: int) -> list[int]:
    """Flat forecast using trailing 14-day moving average."""
    tail = series.tail(_MIN_POINTS).mean() if len(series) >= _MIN_POINTS else series.mean()
    daily = max(0.0, float(tail))
    return [round(daily)] * horizon_days


def _holt_winters_forecast(series: pd.Series, horizon_days: int) -> list[int]:
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
        return [max(0, round(v)) for v in preds]
    except Exception:
        logger.debug("Holt-Winters fit failed — falling back to moving average", exc_info=True)
        return []


class PlanDemandForecaster:
    """Per-plan time-series forecaster (Holt-Winters or moving-average fallback)."""

    def __init__(self, method: str = "holt_winters") -> None:
        if method not in ("holt_winters", "moving_average"):
            raise ValueError(f"Unknown method: {method!r}")
        self.method = method

    def forecast_plan(
        self,
        plan_id: str,
        series: pd.Series,
        horizon_days: int = 90,
    ) -> dict[str, Any]:
        """Forecast daily recharge counts for one plan.

        Parameters
        ----------
        plan_id : str
            Plan UUID (passed through to output).
        series : pd.Series
            Daily recharge counts indexed by date (not necessarily contiguous).
        horizon_days : int
            Number of future days to forecast (default 90).

        Returns
        -------
        dict with keys: plan_id, predicted_uptake_30d, predicted_uptake_60d,
                        predicted_uptake_90d, uptake_trend_90d.
        """
        if len(series) < _MIN_POINTS:
            logger.warning("Plan %s: insufficient history (%d points) — returning zeros", plan_id, len(series))
            return {
                "plan_id": plan_id,
                "predicted_uptake_30d": 0,
                "predicted_uptake_60d": 0,
                "predicted_uptake_90d": 0,
                "uptake_trend_90d": [0] * horizon_days,
            }

        filled = _fill_series(series)
        smoothed = _smooth(filled)

        if self.method == "holt_winters":
            daily_preds = _holt_winters_forecast(smoothed, horizon_days)
            if not daily_preds:
                daily_preds = _moving_average_forecast(smoothed, horizon_days)
        else:
            daily_preds = _moving_average_forecast(smoothed, horizon_days)

        return {
            "plan_id": plan_id,
            "predicted_uptake_30d": int(np.sum(daily_preds[:30])),
            "predicted_uptake_60d": int(np.sum(daily_preds[:60])),
            "predicted_uptake_90d": int(np.sum(daily_preds[:horizon_days])),
            "uptake_trend_90d": daily_preds[:horizon_days],
        }

    def evaluate(self, series: pd.Series) -> dict[str, Any]:
        """Evaluate forecast accuracy on a held-out last-14-day window.

        Parameters
        ----------
        series : pd.Series
            Full historical daily recharge counts.

        Returns
        -------
        dict with keys: mape (float), passed_mape_threshold (bool).
        """
        if len(series) < _MIN_POINTS * 2:
            return {"mape": 0.0, "passed_mape_threshold": True}

        train = series.iloc[:-_HOLDOUT_DAYS]
        actual = series.iloc[-_HOLDOUT_DAYS:]

        filled_train = _fill_series(train)
        smoothed_train = _smooth(filled_train)

        if self.method == "holt_winters":
            preds = _holt_winters_forecast(smoothed_train, _HOLDOUT_DAYS)
            if not preds:
                preds = _moving_average_forecast(smoothed_train, _HOLDOUT_DAYS)
        else:
            preds = _moving_average_forecast(smoothed_train, _HOLDOUT_DAYS)

        actuals = actual.values
        nonzero = actuals != 0
        if not np.any(nonzero):
            return {"mape": 0.0, "passed_mape_threshold": True}

        mape = float(np.mean(np.abs((actuals[nonzero] - np.array(preds)[nonzero]) / actuals[nonzero])) * 100)
        return {"mape": round(mape, 2), "passed_mape_threshold": mape <= _MAPE_THRESHOLD}

    def forecast_all_plans(
        self,
        all_plan_data: dict[str, pd.Series],
    ) -> dict[str, dict[str, Any]]:
        """Run forecast_plan for every plan in *all_plan_data*.

        Plans with fewer than MIN_POINTS data points are included with zero predictions.
        Training errors for individual plans are caught; the failed plan_id is logged and
        returned with zero values so one plan cannot break the whole batch.

        Parameters
        ----------
        all_plan_data : dict[str, pd.Series]
            Map of plan_id → daily recharge count Series.

        Returns
        -------
        dict[str, dict] mapping plan_id → forecast result dict.
        """
        results: dict[str, dict[str, Any]] = {}
        for plan_id, series in all_plan_data.items():
            try:
                results[plan_id] = self.forecast_plan(plan_id, series)
            except Exception:
                logger.exception("Plan %s forecast failed — recording zeros", plan_id)
                results[plan_id] = {
                    "plan_id": plan_id,
                    "predicted_uptake_30d": 0,
                    "predicted_uptake_60d": 0,
                    "predicted_uptake_90d": 0,
                    "uptake_trend_90d": [0] * 90,
                }
        return results


__all__ = ["PlanDemandForecaster"]
