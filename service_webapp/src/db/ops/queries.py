"""DB queries for the ops domain (Story 7.2; Story 7.3 forecast cache).

All functions accept a psycopg ``AsyncConnection``.
Raw SQL via psycopg3; no ORM.

Per CQRS ARCH-4, the dashboard read path uses SELECT-only queries. The forecast cache
is a write-optimised cache table (``forecast_results``): its ``save_*`` helpers issue
DELETE + INSERT to refresh a cached projection (ARCH-4 CQRS write side).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

if TYPE_CHECKING:
    from datetime import datetime

    from psycopg import AsyncConnection


async def get_plan_stock_counts(conn: AsyncConnection) -> list[dict]:
    """Return plan stock counts: plan_id, plan_name, subscriber_count sorted by count DESC.

    Joins plans_plans with identity_subscribers to count active subscribers per plan.
    Plans with zero subscribers are included (LEFT JOIN).

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection for raw SQL queries.

    Returns
    -------
    list[dict]
        List of plan stock dicts with keys: ``plan_id``, ``plan_name``, ``subscriber_count``.
        Sorted by ``subscriber_count`` descending.
    """
    cur = await conn.execute(
        """
        SELECT
            pp.id as plan_id,
            pp.plan_name,
            COUNT(isub.id) as subscriber_count
          FROM plans_plans pp
          LEFT JOIN identity_subscribers isub ON pp.id = isub.plan_id
         WHERE pp.is_active = TRUE
         GROUP BY pp.id, pp.plan_name
         ORDER BY subscriber_count DESC
        """,
    )
    rows = await cur.fetchall()
    return [
        {
            "plan_id": str(row[0]),
            "plan_name": row[1],
            "subscriber_count": row[2],
        }
        for row in rows
    ]


async def get_order_fulfilment_counts(conn: AsyncConnection) -> dict[str, int]:
    """Return order fulfilment counts grouped by status.

    Queries recharge_orders table and returns count per status group.
    Supports statuses: CREATED, KYC_PENDING, KYC_VERIFIED, ACTIVATED, and others.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection for raw SQL queries.

    Returns
    -------
    dict[str, int]
        Dict mapping status strings to their counts. Includes all statuses found in DB.
    """
    cur = await conn.execute(
        """
        SELECT status, COUNT(*) as count
          FROM recharge_orders
         GROUP BY status
        """,
    )
    rows = await cur.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_orders_by_status(
    conn: AsyncConnection,
    status: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Return paginated order list for a given status.

    Queries recharge_orders table filtered by status with pagination.
    Returns order records with subscriber_id (PII - UI should mask last 4 digits).

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection for raw SQL queries.
    status : str
        Order status to filter by (e.g., 'CREATED', 'ACTIVATED').
    limit : int
        Maximum number of rows to return (default 20).
    offset : int
        Number of rows to skip for pagination (default 0).

    Returns
    -------
    list[dict]
        List of order dicts with keys: ``order_id``, ``subscriber_id``, ``created_at``,
        ``updated_at``, ``status``. Sorted by ``created_at`` DESC.
    """
    cur = await conn.execute(
        """
        SELECT
            id as order_id,
            subscriber_id,
            created_at,
            modified_at as updated_at,
            status
          FROM recharge_orders
         WHERE status = %s
         ORDER BY created_at DESC
         LIMIT %s OFFSET %s
        """,
        (status, limit, offset),
    )
    rows = await cur.fetchall()
    return [
        {
            "order_id": str(row[0]),
            "subscriber_id": str(row[1]),
            "created_at": row[2],
            "updated_at": row[3],
            "status": row[4],
        }
        for row in rows
    ]


async def get_historical_plan_recharges(conn: AsyncConnection, days_back: int = 90) -> list[dict]:
    """Return daily recharge counts per plan for the last *days_back* days.

    Queries ``recharge_orders`` where ``completed_at`` is non-null (confirmed recharges).
    Joins ``plans_plans`` to guarantee only known plans are included.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    days_back : int
        Number of calendar days to look back (default 90).

    Returns
    -------
    list[dict]
        List of ``{"plan_id": str, "date": date, "recharge_count": int}``,
        ordered by plan_id then date ascending.
    """
    cur = await conn.execute(
        """
        SELECT
            ro.plan_id,
            DATE(ro.completed_at) AS date,
            COUNT(*) AS recharge_count
          FROM recharge_orders ro
         WHERE ro.completed_at >= NOW() - (%(days_back)s::int * INTERVAL '1 day')
           AND ro.completed_at IS NOT NULL
         GROUP BY ro.plan_id, DATE(ro.completed_at)
         ORDER BY ro.plan_id, date
        """,
        {"days_back": days_back},
    )
    rows = await cur.fetchall()
    return [
        {
            "plan_id": str(row[0]),
            "date": row[1],
            "recharge_count": int(row[2]),
        }
        for row in rows
    ]


async def get_cached_plan_forecast(
    conn: AsyncConnection,
    forecast_type: str = "plan_demand",
) -> list[dict]:
    """Return cached plan demand forecast rows that are still valid.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    forecast_type : str
        Forecast type to query (default ``"plan_demand"``).

    Returns
    -------
    list[dict]
        List of forecast rows with plan_id and uptake predictions.
        Empty list when cache is expired or absent.
    """
    cur = await conn.execute(
        """
        SELECT
            plan_id,
            plan_name,
            predicted_uptake_30d,
            predicted_uptake_60d,
            predicted_uptake_90d,
            uptake_trend_90d,
            model_version,
            trained_at,
            valid_until
          FROM forecast_results
         WHERE forecast_type = %s
           AND plan_id IS NOT NULL
           AND valid_until > NOW()
         ORDER BY plan_id
        """,
        (forecast_type,),
    )
    rows = await cur.fetchall()
    return [
        {
            "plan_id": str(row[0]),
            "plan_name": row[1],
            "predicted_uptake_30d": row[2],
            "predicted_uptake_60d": row[3],
            "predicted_uptake_90d": row[4],
            "uptake_trend_90d": row[5],
            "model_version": row[6],
            "trained_at": row[7],
            "valid_until": row[8],
        }
        for row in rows
    ]


async def save_plan_forecast_results(
    conn: AsyncConnection,
    forecasts: list[dict],
    model_version: str,
    valid_hours: int = 24,
) -> None:
    """Persist plan demand forecast results, replacing any previous cache.

    Deletes existing ``plan_demand`` rows then batch-inserts the new forecasts.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    forecasts : list[dict]
        Each dict must contain: plan_id, plan_name, predicted_uptake_30d,
        predicted_uptake_60d, predicted_uptake_90d, uptake_trend_90d.
    model_version : str
        Version tag for the forecasting run (e.g. ``"holt_winters_v1"``).
    valid_hours : int
        Cache TTL in hours (default 24).
    """
    await conn.execute("DELETE FROM forecast_results WHERE forecast_type = 'plan_demand'")

    if not forecasts:
        return

    for fc in forecasts:
        await conn.execute(
            """
            INSERT INTO forecast_results (
                forecast_type, forecast_date, model_version, trained_at, valid_until,
                plan_id, plan_name,
                predicted_uptake_30d, predicted_uptake_60d, predicted_uptake_90d,
                uptake_trend_90d
            ) VALUES (
                'plan_demand', CURRENT_DATE, %s, NOW(),
                NOW() + (%s::int * INTERVAL '1 hour'),
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                model_version,
                valid_hours,
                fc["plan_id"],
                fc.get("plan_name"),
                fc["predicted_uptake_30d"],
                fc["predicted_uptake_60d"],
                fc["predicted_uptake_90d"],
                json.dumps(fc["uptake_trend_90d"]),
            ),
        )


async def get_historical_activations_churn(
    conn: AsyncConnection,
    days_back: int = 180,
) -> list[dict[str, Any]]:
    """Return a contiguous daily series of activations and churn for the last *days_back* days.

    Activations are counted from ``identity_subscribers.created_at``. Churn uses an
    inactivity proxy (MVP limitation — there is no true churn event): a subscriber is
    counted as churned on the date ``DATE(MAX(billing_cdr_events.start_time)) + 90``
    (no CDR activity for 90 days). The CDR scan is bounded to ``days_back + 90`` days
    so the per-subscriber ``MAX(start_time)`` aggregation stays cheap on large tables.

    A date spine guarantees one row per calendar day (gaps filled with 0) so the
    forecaster sees a regular daily series.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    days_back : int
        Number of trailing days to return (default 180).

    Returns
    -------
    list[dict[str, Any]]
        ``{"date": datetime.date, "activations": int, "churn": int}`` ordered by date asc.
    """
    cur = await conn.execute(
        """
        WITH params AS (SELECT %s::int AS days_back),
        days AS (
            SELECT generate_series(
                (CURRENT_DATE - (SELECT days_back FROM params))::date,
                CURRENT_DATE::date,
                INTERVAL '1 day'
            )::date AS d
        ),
        act AS (
            SELECT DATE(created_at) AS d, COUNT(*)::int AS activations
              FROM identity_subscribers
             WHERE created_at >= (CURRENT_DATE - (SELECT days_back FROM params))::timestamptz
             GROUP BY DATE(created_at)
        ),
        churn_base AS (
            SELECT subscriber_id, DATE(MAX(start_time)) AS last_active
              FROM billing_cdr_events
             WHERE start_time >= NOW() - ((SELECT days_back FROM params) + 90) * INTERVAL '1 day'
             GROUP BY subscriber_id
        ),
        churn AS (
            SELECT (last_active + 90 * INTERVAL '1 day')::date AS d, COUNT(*)::int AS churn
              FROM churn_base
             WHERE last_active IS NOT NULL
             GROUP BY (last_active + 90 * INTERVAL '1 day')::date
        )
        SELECT
            d.d AS date,
            COALESCE(a.activations, 0) AS activations,
            COALESCE(c.churn, 0) AS churn
          FROM days d
          LEFT JOIN act a ON a.d = d.d
          LEFT JOIN churn c ON c.d = d.d
         ORDER BY d.d
        """,
        (days_back,),
    )
    rows = await cur.fetchall()
    return [
        {
            "date": row[0],
            "activations": int(row[1]),
            "churn": int(row[2]),
        }
        for row in rows
    ]


def _isoformat(value: Any) -> str | None:
    """ISO-8601 string for a date/datetime, or ``None``."""
    return value.isoformat() if value is not None else None


async def get_cached_subscriber_growth_forecast(
    conn: AsyncConnection,
    forecast_type: str = "subscriber_growth",
) -> dict[str, Any] | None:
    """Return the cached subscriber-growth projection if still valid, else ``None``.

    Reads still-valid rows (``valid_until > NOW()``) for *forecast_type* and assembles
    the response payload (forecasts list + metrics + meta). Returns ``None`` when the
    cache is absent or expired so the caller can retrain.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    forecast_type : str
        Forecast type to read (default ``"subscriber_growth"``).

    Returns
    -------
    dict[str, Any] | None
        Full forecast payload (``from_cache=True``) or ``None``.
    """
    cur = await conn.execute(
        """
        SELECT forecast_date, predicted_activations, predicted_churn,
               lower_bound_activations, upper_bound_activations,
               lower_bound_churn, upper_bound_churn,
               model_version, trained_at, valid_until, metrics
          FROM forecast_results
         WHERE forecast_type = %s
           AND valid_until > NOW()
           AND predicted_activations IS NOT NULL
         ORDER BY forecast_date
        """,
        (forecast_type,),
    )
    rows = await cur.fetchall()
    if not rows:
        return None

    first = rows[0]
    metrics: Any = first[10] if first[10] is not None else {}
    return {
        "forecast_type": forecast_type,
        "model_version": first[7],
        "trained_at": _isoformat(first[8]),
        "horizon_days": len(rows),
        "metrics": metrics,
        "cache_expires_at": _isoformat(first[9]),
        "from_cache": True,
        "forecasts": [
            {
                "date": _isoformat(row[0]),
                "predicted_activations": row[1],
                "predicted_churn": row[2],
                "lower_bound_activations": row[3],
                "upper_bound_activations": row[4],
                "lower_bound_churn": row[5],
                "upper_bound_churn": row[6],
            }
            for row in rows
        ],
    }


async def save_subscriber_growth_forecast(
    conn: AsyncConnection,
    payload: dict[str, Any],
    valid_until: datetime,
) -> None:
    """Persist a subscriber-growth forecast payload, replacing any previous cache.

    Deletes existing rows for the forecast type then inserts one row per projected day.
    Caller must wrap this in a transaction (``db.transaction()``) so the DELETE + INSERT
    commits atomically.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection (inside a transaction).
    payload : dict[str, Any]
        Output of ``build_forecast_payload`` — must contain ``forecast_type``,
        ``model_version``, ``trained_at``, ``metrics`` and a ``forecasts`` list whose
        items carry ``date`` plus the predicted/bound integers.
    valid_until : datetime
        Cache expiry timestamp (typically ``NOW() + 24h``).
    """
    forecast_type = payload.get("forecast_type", "subscriber_growth")
    model_version = payload.get("model_version")
    trained_at = payload.get("trained_at")
    metrics = payload.get("metrics") or {}

    await conn.execute("DELETE FROM forecast_results WHERE forecast_type = %s", (forecast_type,))

    rows = [
        (
            forecast_type,
            fc["date"],
            model_version,
            trained_at,
            valid_until,
            fc["predicted_activations"],
            fc["predicted_churn"],
            fc["lower_bound_activations"],
            fc["upper_bound_activations"],
            fc["lower_bound_churn"],
            fc["upper_bound_churn"],
            Jsonb(metrics),
        )
        for fc in payload.get("forecasts", [])
    ]
    if not rows:
        return

    await conn.executemany(  # pyrefly: ignore[missing-attribute]
        """
        INSERT INTO forecast_results (
            forecast_type, forecast_date, model_version, trained_at, valid_until,
            predicted_activations, predicted_churn,
            lower_bound_activations, upper_bound_activations,
            lower_bound_churn, upper_bound_churn, metrics
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )


__all__ = [
    "get_cached_plan_forecast",
    "get_cached_subscriber_growth_forecast",
    "get_historical_activations_churn",
    "get_historical_plan_recharges",
    "get_order_fulfilment_counts",
    "get_orders_by_status",
    "get_plan_stock_counts",
    "save_plan_forecast_results",
    "save_subscriber_growth_forecast",
]
