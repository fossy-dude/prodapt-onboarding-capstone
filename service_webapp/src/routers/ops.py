"""Ops dashboard endpoints (Story 7.2 Task 2; Story 7.4).

GET /api/v1/ops/plan-stock              — plan adoption counts (ops role only).
GET /api/v1/ops/orders                  — order fulfilment view (ops role only).
GET /api/v1/ops/forecasts/plan-demand   — 30/60/90-day plan demand forecast (ops + marketing).

All endpoints use SELECT-only queries via ops_queries.py (CQRS ARCH-4).
Role-based access control restricts endpoints per JWT cognito:groups.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse  # noqa: TC002

from core.auth import require_role
from core.errors import DomainError
from core.responses import success_envelope
from db.identity.queries import get_subscriber_id_by_msisdn
from db.ops.queries import (
    get_cached_plan_forecast,
    get_cached_subscriber_growth_forecast,
    get_historical_activations_churn,
    get_historical_plan_recharges,
    get_order_fulfilment_counts,
    get_orders_by_status,
    get_plan_stock_counts,
    save_plan_forecast_results,
    save_subscriber_growth_forecast,
)
from ops.forecasting.plan_demand_model import PlanDemandForecaster
from ops.forecasting.subscriber_growth_model import build_forecast_payload

if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from adapters.postgres import Psycopg3AsyncAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


def _db(request: Request) -> Psycopg3AsyncAdapter:
    """Resolve the database adapter from app state."""
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _trace_id(request: Request) -> str:
    """Return the OTEL trace id from request state, or 'unknown' if absent."""
    return getattr(request.state, "trace_id", "unknown")


# Cognito access tokens carry `username` (= E.164 for phone users); ID tokens
# carry `phone_number` and `cognito:username`. Try all so either token resolves.
_PHONE_CLAIMS = ("phone_number", "username", "cognito:username")


def _extract_msisdn_from_payload(jwt_payload: dict) -> str:
    """Extract msisdn from JWT payload using phone number claims."""
    for claim in _PHONE_CLAIMS:
        value = jwt_payload.get(claim)
        if value:
            return str(value)
    raise ValueError("JWT payload must contain phone number claim (phone_number, username, or cognito:username)")


@router.get("/plan-stock", status_code=200)
async def get_plan_stock(
    request: Request,
    jwt_payload: dict = require_role("ops"),
) -> JSONResponse:
    """Return plan stock counts: plan_id, plan_name, subscriber_count sorted DESC.

    Requires ops role. Returns array of plan adoption metrics.
    Validates msisdn maps to a valid subscriber for consistency with subscriber portal.
    """
    # Extract msisdn from JWT
    try:
        msisdn = _extract_msisdn_from_payload(jwt_payload)
    except ValueError as e:
        logger.warning("Invalid JWT payload for ops endpoint: %s", e)
        raise

    # Validate msisdn maps to a valid subscriber (even though we don't use subscriber_id for queries)
    db = _db(request)
    async with db.connection() as conn:
        subscriber_id = await get_subscriber_id_by_msisdn(conn, msisdn)
        if subscriber_id is None:
            logger.warning("Ops dashboard access by invalid subscriber msisdn: %s", msisdn[-4:])
            # Return empty data rather than error - ops dashboard shows aggregate data anyway
            plans = await get_plan_stock_counts(conn)
        else:
            logger.debug("Ops dashboard access by valid subscriber (msisdn: %s)", msisdn[-4:])
            plans = await get_plan_stock_counts(conn)

    return success_envelope(data=plans, trace_id=_trace_id(request))


@router.get("/orders", status_code=200)
async def get_orders(
    request: Request,
    jwt_payload: dict = require_role("ops"),
    status: str | None = Query(None, description="Filter orders by status"),
    limit: int = Query(20, ge=1, le=100, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> JSONResponse:
    """Return order fulfilment data.

    Without status param: returns status group counts.
    With status param: returns paginated order list for that status.

    Requires ops role. Validates msisdn maps to a valid subscriber for consistency.
    """
    # Extract msisdn from JWT
    try:
        msisdn = _extract_msisdn_from_payload(jwt_payload)
    except ValueError as e:
        logger.warning("Invalid JWT payload for ops endpoint: %s", e)
        raise

    # Validate msisdn maps to a valid subscriber (even though we don't use subscriber_id for queries)
    db = _db(request)
    async with db.connection() as conn:
        subscriber_id = await get_subscriber_id_by_msisdn(conn, msisdn)
        if subscriber_id is None:
            logger.warning("Ops dashboard access by invalid subscriber msisdn: %s", msisdn[-4:])
        else:
            logger.debug("Ops dashboard access by valid subscriber (msisdn: %s)", msisdn[-4:])

        if status:
            # Return paginated order list for specific status
            orders = await get_orders_by_status(conn, status=status, limit=limit, offset=offset)
            return success_envelope(data=orders, trace_id=_trace_id(request))
        else:
            # Return status counts across all orders
            counts = await get_order_fulfilment_counts(conn)
            return success_envelope(data=counts, trace_id=_trace_id(request))


_PLAN_DEMAND_MODEL_VERSION = "holt_winters_v1"


@router.get("/forecasts/plan-demand", status_code=200)
async def get_plan_demand_forecast(
    request: Request,
    jwt_payload: dict = require_role("ops", "marketing"),
    force_refresh: bool = Query(False, description="Bypass cache and regenerate forecasts"),
    plan_ids: list[str] | None = Query(None, description="Optional plan IDs to forecast"),
) -> JSONResponse:
    """Return 30/60/90-day demand forecast per plan.

    Accessible to ops and marketing roles (FR-45).
    Results are cached in Postgres for 24 hours; pass force_refresh=true to regenerate.

    Response JSON::

        {
            "forecasts": [
                {
                    "plan_id": "...",
                    "plan_name": "...",
                    "predicted_uptake_30d": 150,
                    "predicted_uptake_60d": 320,
                    "predicted_uptake_90d": 500,
                    "uptake_trend_90d": [5, 6, 4, ...],
                }
            ],
            "model_version": "holt_winters_v1",
            "trained_at": "...",
            "cache_expires_at": "...",
        }
    """
    db = _db(request)
    selected_plan_ids = list(dict.fromkeys(str(plan_id) for plan_id in (plan_ids or [])))
    has_selected_plans = len(selected_plan_ids) > 0
    async with db.connection() as conn:
        if not force_refresh:
            cached = await get_cached_plan_forecast(conn, plan_ids=selected_plan_ids if has_selected_plans else None)
            cached_plan_ids = {row["plan_id"] for row in cached}
            has_complete_selected_cache = not has_selected_plans or cached_plan_ids == set(selected_plan_ids)
            if cached and has_complete_selected_cache:
                trained_at = cached[0]["trained_at"]
                cache_expires_at = cached[0]["valid_until"]
                return success_envelope(
                    data={
                        "forecasts": [
                            {k: v for k, v in row.items() if k not in ("model_version", "trained_at", "valid_until")}
                            for row in cached
                        ],
                        "model_version": cached[0]["model_version"],
                        "trained_at": trained_at.isoformat() if trained_at else None,
                        "cache_expires_at": cache_expires_at.isoformat() if cache_expires_at else None,
                    },
                    trace_id=_trace_id(request),
                )

        rows = await get_historical_plan_recharges(
            conn,
            days_back=90,
            plan_ids=selected_plan_ids if has_selected_plans else None,
        )

    if not rows and not has_selected_plans:
        logger.warning("No historical recharge data found; returning empty forecast")
        return success_envelope(
            data={
                "forecasts": [],
                "model_version": _PLAN_DEMAND_MODEL_VERSION,
                "trained_at": None,
                "cache_expires_at": None,
            },
            trace_id=_trace_id(request),
        )

    all_plan_data: dict[str, dict] = {plan_id: {} for plan_id in selected_plan_ids}
    for row in rows:
        pid = row["plan_id"]
        if pid not in all_plan_data:
            all_plan_data[pid] = {}
        all_plan_data[pid][row["date"]] = row["recharge_count"]

    series_map: dict[str, pd.Series] = {pid: pd.Series(counts).sort_index() for pid, counts in all_plan_data.items()}

    forecaster = PlanDemandForecaster(method="holt_winters")
    forecast_results = forecaster.forecast_all_plans(series_map)

    async with db.connection() as conn:
        forecast_plan_ids = selected_plan_ids if has_selected_plans else list(forecast_results.keys())
        plan_names = await _get_plan_names(conn, forecast_plan_ids)
        forecasts_with_names = [
            {**fc, "plan_name": plan_names.get(fc["plan_id"], "Unknown Plan")} for fc in forecast_results.values()
        ]
        forecasts_with_names.sort(key=lambda x: x["predicted_uptake_90d"], reverse=True)

        if has_selected_plans:
            trained_at_ts = datetime.now(UTC)
            cache_expires_ts = None
        else:
            await save_plan_forecast_results(conn, forecasts_with_names, _PLAN_DEMAND_MODEL_VERSION)
            cached_after = await get_cached_plan_forecast(conn)
            trained_at_ts = cached_after[0]["trained_at"] if cached_after else None
            cache_expires_ts = cached_after[0]["valid_until"] if cached_after else None

    return success_envelope(
        data={
            "forecasts": forecasts_with_names,
            "model_version": _PLAN_DEMAND_MODEL_VERSION,
            "trained_at": trained_at_ts.isoformat() if trained_at_ts else None,
            "cache_expires_at": cache_expires_ts.isoformat() if cache_expires_ts else None,
        },
        trace_id=_trace_id(request),
    )


async def _get_plan_names(conn: AsyncConnection, plan_ids: list[str]) -> dict[str, str]:
    """Fetch plan_name for each plan_id from plans_plans."""
    if not plan_ids:
        return {}
    cur = await conn.execute(
        "SELECT id, plan_name FROM plans_plans WHERE id = ANY(%s)",
        (plan_ids,),
    )
    rows = await cur.fetchall()
    return {str(row[0]): row[1] for row in rows}


_SUBSCRIBER_GROWTH_FORECAST_TYPE = "subscriber_growth"
_MIN_HISTORY_DAYS = 90
_FORECAST_HORIZON_DAYS = 90
_FORECAST_HOLDOUT_DAYS = 30
_FORECAST_CACHE_HOURS = 24


@router.get("/forecasts/subscriber-growth", status_code=200)
async def get_subscriber_growth_forecast(
    request: Request,
    jwt_payload: dict = require_role("ops"),
    force_refresh: bool = Query(False, description="Bypass cache and retrain the model"),
) -> JSONResponse:
    """Return a 90-day subscriber activations + churn forecast with 95% confidence intervals.

    Requires the ``ops`` role (AC #7). Results are cached in Postgres for 24h (AC #5);
    pass ``force_refresh=true`` to bypass the cache and retrain. Requires at least 90
    days of historical activation data (AC #1) — returns 400 otherwise. MAPE < 15%
    (NFR-14) is a soft gate: a holdout MAPE above threshold is logged but the forecast
    is still returned (the eval harness in Story 7.1 owns the hard gate).

    Response ``data``: ``forecasts`` (90 daily points with predicted_activations,
    predicted_churn and lower/upper bounds), ``model_version``, ``trained_at``,
    ``cache_expires_at``, ``from_cache`` and ``metrics`` (holdout MAPE).
    """
    db = _db(request)

    # 1. Serve the cached projection when fresh and not forced to refresh.
    if not force_refresh:
        async with db.connection() as conn:
            cached = await get_cached_subscriber_growth_forecast(conn)
        if cached is not None:
            return success_envelope(data=cached, trace_id=_trace_id(request))

    # 2. Cache miss / forced refresh: gather history and validate sufficiency (AC #1).
    async with db.connection() as conn:
        history = await get_historical_activations_churn(conn, days_back=180)

    active_days = sum(1 for row in history if row["activations"] > 0)
    if active_days < _MIN_HISTORY_DAYS:
        err = DomainError(
            f"Insufficient historical data: need >= {_MIN_HISTORY_DAYS} days of activations, found {active_days}.",
            detail={"days_available": active_days, "days_required": _MIN_HISTORY_DAYS},
        )
        err.code = "INSUFFICIENT_FORECAST_DATA"
        raise err

    # 3. Train + evaluate (soft MAPE gate) + predict. Any model failure degrades to a
    #    clean 500 envelope instead of an unhandled traceback (Task 10).
    try:
        payload = build_forecast_payload(
            history,
            horizon_days=_FORECAST_HORIZON_DAYS,
            holdout_days=_FORECAST_HOLDOUT_DAYS,
        )
    except Exception as exc:
        logger.exception("subscriber_growth_forecast: generation failed")
        err = DomainError("Subscriber growth forecast could not be generated.")
        err.code = "FORECAST_GENERATION_FAILED"
        err.http_status = 500
        raise err from exc

    # 4. Persist to the cache. Transactional so the DELETE + INSERT commits atomically;
    #    a cache-write failure is non-fatal — the forecast is still returned.
    valid_until = datetime.now(UTC) + timedelta(hours=_FORECAST_CACHE_HOURS)
    try:
        async with db.transaction() as conn:
            await save_subscriber_growth_forecast(conn, payload, valid_until)
    except Exception as exc:
        logger.warning("subscriber_growth_forecast: cache write failed (returning uncached): %s", exc)

    response_payload = {
        **payload,
        "cache_expires_at": valid_until.isoformat(),
        "from_cache": False,
    }
    return success_envelope(data=response_payload, trace_id=_trace_id(request))
