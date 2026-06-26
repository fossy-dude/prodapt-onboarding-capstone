"""Daily forecast retraining jobs (Story 7.3 + Story 7.4).

Subscriber growth (Story 7.3) retrains at 02:00 UTC; plan demand (Story 7.4) at 03:00
UTC — staggered to spread DB load. Each job calls the same logic as its API endpoint
but inline, so no HTTP round-trip is needed.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from db.ops.queries import (
    get_historical_activations_churn,
    get_historical_plan_recharges,
    save_plan_forecast_results,
    save_subscriber_growth_forecast,
)
from ops.forecasting.plan_demand_model import PlanDemandForecaster
from ops.forecasting.subscriber_growth_model import MAPE_THRESHOLD, build_forecast_payload

if TYPE_CHECKING:
    from adapters.postgres import Psycopg3AsyncAdapter

logger = logging.getLogger(__name__)


async def retrain_plan_demand_forecast(db: Psycopg3AsyncAdapter) -> None:
    """Retrain per-plan demand forecast and persist to forecast_results.

    Fetches the last 90 days of recharge history, runs Holt-Winters per plan,
    and saves results.  Per-plan MAPE is logged; plans exceeding 25% threshold
    emit a warning for alerting.

    Parameters
    ----------
    db : Psycopg3AsyncAdapter
        Live database adapter injected by the scheduler setup.
    """
    start = time.monotonic()
    logger.info("plan_demand_forecast: retraining job started")

    async with db.connection() as conn:
        rows = await get_historical_plan_recharges(conn, days_back=90)

    if not rows:
        logger.warning("plan_demand_forecast: no recharge history found; skipping")
        return

    all_plan_data: dict[str, dict] = {}
    for row in rows:
        pid = row["plan_id"]
        if pid not in all_plan_data:
            all_plan_data[pid] = {}
        all_plan_data[pid][row["date"]] = row["recharge_count"]

    series_map: dict[str, pd.Series] = {pid: pd.Series(counts).sort_index() for pid, counts in all_plan_data.items()}

    forecaster = PlanDemandForecaster(method="holt_winters")
    forecast_results = forecaster.forecast_all_plans(series_map)

    high_mape_plans: list[str] = []
    for plan_id, series in series_map.items():
        metrics = forecaster.evaluate(series)
        if not metrics["passed_mape_threshold"]:
            high_mape_plans.append(plan_id)
            logger.warning(
                "plan_demand_forecast: plan %s MAPE=%.1f%% exceeds 25%% threshold",
                plan_id,
                metrics["mape"],
            )

    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT id, plan_name FROM plans_plans WHERE id = ANY(%s)",
            (list(forecast_results.keys()),),
        )
        plan_name_rows = await cur.fetchall()
        plan_names = {str(r[0]): r[1] for r in plan_name_rows}

        forecasts_with_names = [
            {**fc, "plan_name": plan_names.get(fc["plan_id"], "Unknown Plan")} for fc in forecast_results.values()
        ]
        await save_plan_forecast_results(conn, forecasts_with_names, "holt_winters_v1")

    elapsed = time.monotonic() - start
    logger.info(
        "plan_demand_forecast: done. plans=%d high_mape=%d duration=%.1fs",
        len(forecast_results),
        len(high_mape_plans),
        elapsed,
    )


def register_plan_demand_job(scheduler: object, db: Psycopg3AsyncAdapter) -> None:
    """Register the daily plan demand retraining cron with *scheduler*.

    Parameters
    ----------
    scheduler : AsyncIOScheduler
        APScheduler instance (already started or about to start).
    db : Psycopg3AsyncAdapter
        Database adapter passed through to the job coroutine.
    """
    scheduler.add_job(  # type: ignore[attr-defined]
        retrain_plan_demand_forecast,
        trigger="cron",
        hour=3,
        minute=0,
        kwargs={"db": db},
        id="plan_demand_forecast_retrain",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("plan_demand_forecast: daily retrain job registered (03:00)")


# Subscriber-growth retrain (Story 7.3). Consecutive-failure tracking so a stuck job
# escalates to an error log for ops after _ALERT_AFTER_FAILURES days (Task 10).
_consecutive_failures = 0
_ALERT_AFTER_FAILURES = 3


def _record_retrain_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def _record_retrain_failure() -> None:
    global _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures >= _ALERT_AFTER_FAILURES:
        logger.error(
            "subscriber_growth_forecast: %d consecutive retrain failures — ops intervention required",
            _consecutive_failures,
        )


async def retrain_subscriber_growth_forecast(db: Psycopg3AsyncAdapter) -> None:
    """Retrain the subscriber-growth forecast and persist it to ``forecast_results``.

    Fetches 180 days of activations/churn, trains + evaluates (soft MAPE gate) +
    predicts 90 days, and saves the cache (24h TTL). Logs model version, MAPE and
    duration; warns on MAPE threshold breach. Failures are caught and logged so the
    scheduler keeps running; after 3 consecutive failures an error is logged for ops.

    Parameters
    ----------
    db : Psycopg3AsyncAdapter
        Live database adapter injected by the scheduler setup.
    """
    start = time.monotonic()
    logger.info("subscriber_growth_forecast: retraining job started")

    try:
        async with db.connection() as conn:
            history = await get_historical_activations_churn(conn, days_back=180)

        active_days = sum(1 for row in history if row["activations"] > 0)
        if active_days < 90:
            logger.warning(
                "subscriber_growth_forecast: insufficient history (%d active days); skipping",
                active_days,
            )
            _record_retrain_failure()
            return

        payload = build_forecast_payload(history, horizon_days=90, holdout_days=30)
        valid_until = datetime.now(UTC) + timedelta(hours=24)

        async with db.transaction() as conn:
            await save_subscriber_growth_forecast(conn, payload, valid_until)

        metrics = payload.get("metrics", {})
        elapsed = time.monotonic() - start
        logger.info(
            "subscriber_growth_forecast: done. model=%s mape_act=%.2f mape_churn=%.2f duration=%.1fs",
            payload.get("model_version"),
            metrics.get("mape_activations", 0.0),
            metrics.get("mape_churn", 0.0),
            elapsed,
        )
        if not metrics.get("passed_mape_threshold", True):
            logger.warning(
                "subscriber_growth_forecast: MAPE exceeds %.1f%% threshold (act=%.2f churn=%.2f)",
                MAPE_THRESHOLD,
                metrics.get("mape_activations", 0.0),
                metrics.get("mape_churn", 0.0),
            )
        _record_retrain_success()
    except Exception:
        _record_retrain_failure()
        logger.exception("subscriber_growth_forecast: retraining job failed")


def register_subscriber_growth_job(scheduler: object, db: Psycopg3AsyncAdapter) -> None:
    """Register the daily subscriber-growth retraining cron with *scheduler*.

    Parameters
    ----------
    scheduler : AsyncIOScheduler
        APScheduler instance (already started or about to start).
    db : Psycopg3AsyncAdapter
        Database adapter passed through to the job coroutine.
    """
    scheduler.add_job(  # type: ignore[attr-defined]
        retrain_subscriber_growth_forecast,
        trigger="cron",
        hour=2,
        minute=0,
        timezone="UTC",
        kwargs={"db": db},
        id="subscriber_growth_forecast_retrain",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("subscriber_growth_forecast: daily retrain job registered (02:00 UTC)")


__all__ = [
    "register_plan_demand_job",
    "register_subscriber_growth_job",
    "retrain_plan_demand_forecast",
    "retrain_subscriber_growth_forecast",
]
