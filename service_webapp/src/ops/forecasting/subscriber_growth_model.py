"""Subscriber growth forecaster using scikit-learn (Story 7.3).

Forecasts daily subscriber activations and churn 90 days ahead with 95% confidence
intervals. Uses ``GradientBoostingRegressor`` (captures non-linear trend plus
weekly/monthly seasonality) with a ``LinearRegression`` fallback when the boosting
fit fails or history is sparse. Confidence intervals use a bootstrap of training
residuals (Dev Notes Method 2) — fast and sufficient for the MVP. The forecaster is
model-agnostic so a future upgrade to Prophet / TimesFM / Chronos is a drop-in swap
inside :class:`SubscriberGrowthForecaster`.

MAPE < 15% (NFR-14) is enforced as a *soft* gate here (log warning, still return);
the eval harness (Story 7.1) owns the hard gate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor  # pyrefly: ignore[missing-import]
from sklearn.linear_model import LinearRegression  # pyrefly: ignore[missing-import]

logger = logging.getLogger(__name__)

# NFR-14: forecasting quality target.
MAPE_THRESHOLD = 15.0

_MIN_TRAIN_POINTS = 30
_DEFAULT_HORIZON = 90
_DEFAULT_HOLDOUT = 30
_BOOTSTRAP_SAMPLES = 200
_RANDOM_STATE = 42

# In-process cache of the last fully-trained forecaster so a burst of cache-miss
# requests reuse the model instead of retraining (Story 7.3 Task 9). Keyed by the
# forecast type + a data signature (row count, min/max date); a stale signature
# (new day's data) invalidates automatically. The DB forecast cache (forecast_results)
# remains the primary cache; this is a secondary optimisation only.
_TRAINED_CACHE: dict[str, tuple[str, SubscriberGrowthForecaster]] = {}


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error, ignoring zero-actual points.

    Zero-actual days (e.g. the churn proxy trailing off) would otherwise divide by
    zero; they are excluded. If every actual is zero, MAPE is defined as 0.0 (a flat
    zero series is trivially "perfect").
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    nonzero = actual != 0
    if not np.any(nonzero):
        return 0.0
    return float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)


def _engineer_features(dates: pd.Series, origin: pd.Timestamp) -> pd.DataFrame:
    """Build trend + seasonality features for *dates* relative to *origin*.

    Features: continuous time index ``t`` (days since origin), ``day_of_week``,
    ``day_of_month``, ``week_of_year``, ``month``, and an ``is_weekend`` flag. ``t``
    uses the same origin for train and predict so the trend extrapolates forward.
    """
    ts = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "t": (ts - origin).dt.days.astype(float),
            "day_of_week": ts.dt.dayofweek.astype(float),
            "day_of_month": ts.dt.day.astype(float),
            "week_of_year": ts.dt.isocalendar().week.astype(float),
            "month": ts.dt.month.astype(float),
            "is_weekend": ts.dt.dayofweek.isin([5, 6]).astype(float),
        }
    )


def _make_regressor(model_type: str) -> Any:
    if model_type == "gradient_boosting":
        return GradientBoostingRegressor(n_estimators=100, max_depth=3, random_state=_RANDOM_STATE)
    if model_type == "linear":
        return LinearRegression()
    raise ValueError(f"Unknown model_type: {model_type!r}")


class SubscriberGrowthForecaster:
    """Daily activations + churn forecaster with bootstrap 95% confidence intervals."""

    def __init__(self, model_type: str = "gradient_boosting") -> None:
        if model_type not in ("gradient_boosting", "linear"):
            raise ValueError(f"Unknown model_type: {model_type!r}")
        self.model_type = model_type
        # Actual model used after any GradientBoosting -> Linear fallback.
        self.effective_model_type: str = model_type
        self._origin: pd.Timestamp | None = None
        self._last_date: pd.Timestamp | None = None
        self._model_act: Any = None
        self._model_churn: Any = None
        self._resid_act: np.ndarray | None = None
        self._resid_churn: np.ndarray | None = None

    def _fit_series(self, X: pd.DataFrame, y: np.ndarray, label: str) -> tuple[Any, np.ndarray]:
        """Fit one regressor, falling back to LinearRegression if GradientBoosting fails."""
        model = _make_regressor(self.model_type)
        try:
            model.fit(X, y)
            if self.model_type == "gradient_boosting":
                self.effective_model_type = "gradient_boosting"
        except Exception as exc:
            if self.model_type != "gradient_boosting":
                raise
            logger.warning(
                "subscriber_growth: GradientBoosting fit failed for %s (%s) — falling back to LinearRegression",
                label,
                exc,
            )
            model = LinearRegression()
            model.fit(X, y)
            self.effective_model_type = "linear"
        residuals = y - np.asarray(model.predict(X), dtype=float)
        return model, residuals

    def _predict_series(
        self, model: Any, residuals: np.ndarray | None, X: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Point predictions + bootstrap 2.5/97.5 percentile bounds."""
        point = np.asarray(model.predict(X), dtype=float)
        if residuals is None or len(residuals) == 0 or not np.any(residuals):
            lower = point.copy()
            upper = point.copy()
        else:
            rng = np.random.default_rng(_RANDOM_STATE)
            samples = point[:, None] + rng.choice(residuals, size=(point.shape[0], _BOOTSTRAP_SAMPLES))
            lower = np.percentile(samples, 2.5, axis=1)
            upper = np.percentile(samples, 97.5, axis=1)
        # Guarantee lower <= point <= upper (bootstrap percentiles can cross for flat series).
        lower = np.minimum(lower, point)
        upper = np.maximum(upper, point)
        return point, lower, upper

    def train(self, historical_data: pd.DataFrame) -> None:
        """Fit activations + churn models on daily counts.

        Parameters
        ----------
        historical_data : pd.DataFrame
            Columns ``date, activations, churn``. ``date`` may be any parseable form;
            rows are sorted and de-duplicated by date.
        """
        df = historical_data.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
        if len(df) < _MIN_TRAIN_POINTS:
            raise ValueError(f"Need >= {_MIN_TRAIN_POINTS} daily points to train, got {len(df)}")

        self._origin = df["date"].min()
        self._last_date = df["date"].max()
        X = _engineer_features(df["date"], self._origin)
        self._model_act, self._resid_act = self._fit_series(
            X, df["activations"].astype(float).to_numpy(), "activations"
        )
        self._model_churn, self._resid_churn = self._fit_series(X, df["churn"].astype(float).to_numpy(), "churn")

    def predict(self, horizon_days: int = _DEFAULT_HORIZON) -> pd.DataFrame:
        """Return a ``horizon_days``-row forecast DataFrame starting the day after training."""
        if self._last_date is None or self._origin is None:
            raise RuntimeError("SubscriberGrowthForecaster.predict called before train()")

        future = pd.date_range(self._last_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")
        X = _engineer_features(pd.Series(future), self._origin)
        pa, la, ua = self._predict_series(self._model_act, self._resid_act, X)
        pc, lc, uc = self._predict_series(self._model_churn, self._resid_churn, X)

        def _clip_int(arr: np.ndarray) -> np.ndarray:
            return np.clip(np.rint(arr), 0, None).astype(int)

        return pd.DataFrame(
            {
                "date": future,
                "predicted_activations": _clip_int(pa),
                "predicted_churn": _clip_int(pc),
                "lower_bound_activations": _clip_int(la),
                "upper_bound_activations": _clip_int(ua),
                "lower_bound_churn": _clip_int(lc),
                "upper_bound_churn": _clip_int(uc),
            }
        )

    def evaluate(self, actual_data: pd.DataFrame) -> dict[str, Any]:
        """Compute MAPE for activations + churn over *actual_data* using the trained models.

        Returns ``{mape_activations, mape_churn, passed_mape_threshold}``.
        """
        if self._origin is None:
            raise RuntimeError("SubscriberGrowthForecaster.evaluate called before train()")
        df = actual_data.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
        X = _engineer_features(df["date"], self._origin)
        mape_act = _mape(df["activations"].astype(float).to_numpy(), self._model_act.predict(X))
        mape_churn = _mape(df["churn"].astype(float).to_numpy(), self._model_churn.predict(X))
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


def _data_signature(df: pd.DataFrame) -> str:
    """Cheap signature to detect new data and invalidate the in-memory model cache."""
    return f"{len(df)}:{df['date'].min().date()}:{df['date'].max().date()}"


def build_forecast_payload(
    historical_rows: list[dict[str, Any]],
    *,
    horizon_days: int = _DEFAULT_HORIZON,
    holdout_days: int = _DEFAULT_HOLDOUT,
    model_type: str = "gradient_boosting",
) -> dict[str, Any]:
    """Train, evaluate (soft MAPE gate), and produce a 90-day forecast payload.

    This is the shared orchestration used by both the API endpoint (cache miss) and
    the daily retraining job. Returns the payload stored in ``ops_forecast_results``
    (under ``forecasts``/``metrics``); the caller adds ``cache_expires_at`` /
    ``from_cache`` for the HTTP response.

    A 30-day trailing holdout evaluates accuracy (soft gate: log warning on MAPE >
    15%, still return). The final projection is then trained on the full history.
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
    # Holdout evaluation only when there is enough data beyond the holdout window.
    if len(df) > holdout_days + _MIN_TRAIN_POINTS:
        train_df = df.iloc[:-holdout_days]
        holdout_df = df.iloc[-holdout_days:]
        try:
            evaluator = SubscriberGrowthForecaster(model_type=model_type)
            evaluator.train(train_df)
            holdout_metrics = evaluator.evaluate(holdout_df)
            metrics.update(
                mape_activations=round(holdout_metrics["mape_activations"], 2),
                mape_churn=round(holdout_metrics["mape_churn"], 2),
                passed_mape_threshold=bool(holdout_metrics["passed_mape_threshold"]),
            )
        except Exception as exc:
            logger.warning("subscriber_growth: holdout evaluation failed: %s", exc)

    # Final model trained on ALL history (reuse from in-memory cache when unchanged).
    signature = _data_signature(df)
    cached = _TRAINED_CACHE.get("subscriber_growth")
    if cached is not None and cached[0] == signature:
        forecaster = cached[1]
    else:
        forecaster = SubscriberGrowthForecaster(model_type=model_type)
        forecaster.train(df)
        _TRAINED_CACHE["subscriber_growth"] = (signature, forecaster)

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
        "model_version": f"{forecaster.effective_model_type}_v1",
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
