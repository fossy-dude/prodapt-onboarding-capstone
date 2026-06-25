"""Read-only CQRS queries for billing domain (Story 3.2; architecture §1.11.2 CQRS).

All functions accept a psycopg ``AsyncConnection`` (from ``db.transaction()``).
Raw SQL via psycopg3; no ORM.

Usage data: sourced from ``billing_cdr_events`` (written by Story 2.2).
No ``billing_usage_summary`` view exists in V1 migrations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import AsyncConnection


async def get_wallet_balance_from_db(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> dict | None:
    """Return balance row from ``billing_wallet_balances`` or ``None`` if absent.

    Fallback for cold Valkey cache (architecture §1.7.3).
    """
    cur = await conn.execute(
        """
        SELECT balance_paise, msisdn, last_recharge_at, last_deduction_at
          FROM billing_wallet_balances
         WHERE subscriber_id = %s::uuid
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "balance_paise": row[0],
        "msisdn": row[1],
        "last_recharge_at": row[2],
        "last_deduction_at": row[3],
    }


async def get_msisdn_for_subscriber(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> str | None:
    """Return the MSISDN for a subscriber UUID, or ``None`` if not found."""
    cur = await conn.execute(
        """
        SELECT msisdn FROM identity_subscribers WHERE id = %s::uuid
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def get_transactions_page(
    conn: AsyncConnection,
    subscriber_id: UUID,
    cursor: UUID | None = None,
    page_size: int = 20,
) -> list[dict]:
    """Return one page of ``billing_transactions`` (newest first), keyset-paginated.

    Fetches ``page_size + 1`` rows so the caller can detect whether a next page
    exists. UUIDv7 ids are time-monotonic, so the ledger is ordered and
    keyset-paged purely on ``id`` (``ORDER BY id DESC`` + ``id < cursor``).
    Keeping the sort key and the keyset predicate on the same column guarantees
    no row is skipped or duplicated across pages (created_at comes from NOW(),
    frozen at transaction begin, and can disagree with the uuid_generate_v7()
    insert timestamp under concurrent writers) — Story 3.3 cursor contract.

    Raw ``reference_type`` / ``reference_id`` are returned; the endpoint derives
    ``cdr_reference`` (``reference_id`` where ``reference_type = 'cdr'``) — there is
    no ``cdr_reference`` column (V1:218-230).
    """
    limit = page_size + 1
    if cursor is None:
        cur = await conn.execute(
            """
            SELECT id, transaction_type, amount_paise, balance_after_paise,
                   reference_type, reference_id, description, created_at
              FROM billing_transactions
             WHERE subscriber_id = %s::uuid
             ORDER BY id DESC
             LIMIT %s
            """,
            (str(subscriber_id), limit),
        )
    else:
        cur = await conn.execute(
            """
            SELECT id, transaction_type, amount_paise, balance_after_paise,
                   reference_type, reference_id, description, created_at
              FROM billing_transactions
             WHERE subscriber_id = %s::uuid
               AND id < %s::uuid
             ORDER BY id DESC
             LIMIT %s
            """,
            (str(subscriber_id), str(cursor), limit),
        )
    rows = await cur.fetchall()
    return [
        {
            "id": row[0],
            "transaction_type": row[1],
            "amount_paise": row[2],
            "balance_after_paise": row[3],
            "reference_type": row[4],
            "reference_id": row[5],
            "description": row[6],
            "created_at": row[7],
        }
        for row in rows
    ]


async def get_active_subscription(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> dict | None:
    """Return the active plan subscription and its allowances, or ``None``."""
    cur = await conn.execute(
        """
        SELECT
            ps.id,
            ps.plan_id,
            ps.start_date,
            ps.end_date,
            pp.voice_minutes,
            pp.data_limit_mb,
            pp.sms_count
          FROM plans_subscriptions ps
          JOIN plans_plans pp ON pp.id = ps.plan_id
         WHERE ps.subscriber_id = %s::uuid
           AND ps.status = 'active'
         ORDER BY ps.start_date DESC, ps.id DESC
         LIMIT 1
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "subscription_id": row[0],
        "plan_id": row[1],
        "start_date": row[2],
        "end_date": row[3],
        "voice_minutes_allowance": row[4],
        "data_limit_mb_allowance": row[5],
        "sms_count_allowance": row[6],
    }


async def get_active_plan(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> dict | None:
    """Return the active plan's name, validity and quotas, or ``None`` (Story 3.4).

    Joins the latest active ``plans_subscriptions`` to its ``plans_plans`` row.
    ``days_remaining`` is computed by the caller from ``end_date`` (now-relative).
    """
    cur = await conn.execute(
        """
        SELECT
            ps.plan_id,
            pp.plan_name,
            ps.end_date,
            pp.validity_days,
            pp.data_limit_mb,
            pp.voice_minutes,
            pp.sms_count
          FROM plans_subscriptions ps
          JOIN plans_plans pp ON pp.id = ps.plan_id
         WHERE ps.subscriber_id = %s::uuid
           AND ps.status = 'active'
         ORDER BY ps.start_date DESC, ps.id DESC
         LIMIT 1
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "plan_id": row[0],
        "plan_name": row[1],
        "end_date": row[2],
        "validity_days": row[3],
        "data_limit_mb": row[4],
        "voice_minutes": row[5],
        "sms_count": row[6],
    }


async def get_usage_for_period(
    conn: AsyncConnection,
    subscriber_id: UUID,
    start_date: datetime,
    end_date: datetime | None,
) -> dict:
    """Aggregate per-type CDR usage from ``billing_cdr_events`` for the plan window.

    Returns: ``{voice_minutes_used, data_mb_used, sms_count_used, roaming_mb_used}``
    """
    if end_date is not None:
        cur = await conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN cdr_type = 'voice' THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0) / 60.0 AS voice_minutes_used,
                COALESCE(SUM(CASE WHEN cdr_type = 'data'  THEN COALESCE(volume_mb, 0) ELSE 0 END), 0)              AS data_mb_used,
                COALESCE(SUM(CASE WHEN cdr_type = 'sms'   THEN 1 ELSE 0 END), 0)                                   AS sms_count_used,
                COALESCE(SUM(CASE WHEN roaming = TRUE      THEN COALESCE(volume_mb, 0) ELSE 0 END), 0)              AS roaming_mb_used
              FROM billing_cdr_events
             WHERE subscriber_id = %s::uuid
               AND start_time >= %s::timestamptz
               AND start_time <= %s::timestamptz
               AND status = 'charged'
            """,
            (str(subscriber_id), start_date, end_date),
        )
    else:
        cur = await conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN cdr_type = 'voice' THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0) / 60.0 AS voice_minutes_used,
                COALESCE(SUM(CASE WHEN cdr_type = 'data'  THEN COALESCE(volume_mb, 0) ELSE 0 END), 0)              AS data_mb_used,
                COALESCE(SUM(CASE WHEN cdr_type = 'sms'   THEN 1 ELSE 0 END), 0)                                   AS sms_count_used,
                COALESCE(SUM(CASE WHEN roaming = TRUE      THEN COALESCE(volume_mb, 0) ELSE 0 END), 0)              AS roaming_mb_used
              FROM billing_cdr_events
             WHERE subscriber_id = %s::uuid
               AND start_time >= %s::timestamptz
               AND status = 'charged'
            """,
            (str(subscriber_id), start_date),
        )
    row = await cur.fetchone()
    if row is None:
        return {
            "voice_minutes_used": 0.0,
            "data_mb_used": 0.0,
            "sms_count_used": 0,
            "roaming_mb_used": 0.0,
        }
    return {
        "voice_minutes_used": float(row[0]),
        "data_mb_used": float(row[1]),
        "sms_count_used": int(row[2]),
        "roaming_mb_used": float(row[3]),
    }


async def get_active_plan_data_quota(
    conn: AsyncConnection,
    subscriber_id: str,
) -> tuple[float, float] | None:
    """Get active plan data quota and usage for DATA_NUDGE (Story 4.1, Task 4).

    Returns (data_mb_used, data_limit_mb) or None if:
    - No active subscription found
    - Unlimited data plan (data_limit_mb = 0)

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection for raw SQL queries.
    subscriber_id : str
        Subscriber UUID string.

    Returns
    -------
    tuple[float, float] | None
        (data_mb_used, data_limit_mb) or None for no quota.
    """
    # Get active subscription with plan details
    cur = await conn.execute(
        """
        SELECT
            ps.id,
            pp.data_limit_mb,
            ps.start_date,
            ps.end_date
        FROM plans_subscriptions ps
        JOIN plans_plans pp ON ps.plan_id = pp.id
        WHERE ps.subscriber_id = %s::uuid
          AND ps.status = 'active'
        ORDER BY ps.created_at DESC
        LIMIT 1
        """,
        (subscriber_id,),
    )

    row = await cur.fetchone()
    if row is None:
        return None

    _subscription_id, data_limit_mb, start_date, end_date = row

    # Unlimited plan check (data_limit_mb = 0 or NULL)
    if data_limit_mb is None or data_limit_mb == 0:
        return None

    # Sum data usage from billing_cdr_events for the plan window
    cur = await conn.execute(
        """
        SELECT SUM(volume_mb)
        FROM billing_cdr_events
        WHERE subscriber_id = %s::uuid
          AND cdr_type = 'data'
          AND start_time >= %s
          AND (start_time <= %s OR %s IS NULL)
        """,
        (subscriber_id, start_date, end_date, end_date),
    )

    usage_row = await cur.fetchone()
    if usage_row is None:
        return (0.0, data_limit_mb)
    data_mb_used = float(usage_row[0]) if usage_row[0] is not None else 0.0

    return (data_mb_used, data_limit_mb)


async def get_charge_breakdown(
    conn: AsyncConnection,
    subscriber_id: str | UUID,
    cdr_reference: str | UUID,
) -> dict | None:
    """Fetch charge breakdown for a specific CDR event (Story 5.7).

    Queries billing_cdr_events joined with active plan subscription and
    plan configuration to retrieve detailed charge breakdown including
    per-unit rates and balance impact.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection for raw SQL queries.
    subscriber_id : str | UUID
        Subscriber UUID to query CDR for.
    cdr_reference : str | UUID
        CDR event ID to fetch breakdown for.

    Returns
    -------
    dict | None
        Structured breakdown data or None if CDR not found:
        {
            "cdr_id": str,
            "event_type": str,
            "duration_or_data": str,
            "rate_per_unit": int,
            "charge_paise": int,
            "balance_before": int,
            "balance_after": int
        }
    """
    # Query CDR event with active subscription and plan details
    cur = await conn.execute(
        """
        SELECT
            cdr.id as cdr_id,
            cdr.cdr_type as event_type,
            cdr.duration_seconds,
            cdr.volume_mb,
            cdr.cost_paise as charge_paise,
            cdr.start_time,
            pp.plan_name,
            pp.voice_minutes,
            pp.data_limit_mb,
            pp.sms_count
        FROM billing_cdr_events cdr
        JOIN identity_subscribers sub ON sub.id = cdr.subscriber_id
        LEFT JOIN plans_subscriptions ps ON ps.subscriber_id = sub.id
            AND ps.status = 'active'
        LEFT JOIN plans_plans pp ON pp.id = ps.plan_id
        WHERE cdr.id = %s::uuid
          AND cdr.subscriber_id = %s::uuid
          AND cdr.status = 'rated'
        LIMIT 1
        """,
        (str(cdr_reference), str(subscriber_id)),
    )

    row = await cur.fetchone()
    if row is None:
        return None

    (
        cdr_id,
        event_type,
        duration_seconds,
        volume_mb,
        charge_paise,
        _start_time,
        _plan_name,
        _voice_minutes,
        _data_limit_mb,
        _sms_count,
    ) = row

    # Get per-unit rates from plan config (fallback to defaults if not configured)
    rate_per_unit = await _get_rate_from_config(
        conn,
        str(row[7]),  # plan_id from subscription would be better, but using defaults
        event_type,
    )

    # Format duration_or_data based on event type
    if event_type == "voice" and duration_seconds is not None:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_or_data = f"{minutes}m {seconds}s"
    elif event_type == "data" and volume_mb is not None:
        duration_or_data = f"{volume_mb:.2f}MB"
    elif event_type == "sms":
        duration_or_data = "1 SMS"
    else:
        duration_or_data = "Unknown"

    # Get balance before/after from billing_transactions
    balance_before, balance_after = await _get_balance_impact(
        conn,
        subscriber_id,
        cdr_id,
    )

    return {
        "cdr_id": str(cdr_id),
        "event_type": event_type,
        "duration_or_data": duration_or_data,
        "rate_per_unit": rate_per_unit,
        "charge_paise": charge_paise,
        "balance_before": balance_before,
        "balance_after": balance_after,
    }


async def _get_rate_from_config(
    conn: AsyncConnection,
    plan_id: str,
    event_type: str,
) -> int:
    """Get per-unit rate from plan configuration (Story 5.7).

    Fetches rate from plans_plan_config table. Returns default rates
    if not configured (voice: 50p/min, data: 10p/MB, SMS: 100p/SMS).

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    plan_id : str
        Plan UUID to get rate for.
    event_type : str
        Event type: 'voice', 'data', or 'sms'.

    Returns
    -------
    int
        Rate per unit in paise.
    """
    config_key = f"{event_type}_rate_paise"

    cur = await conn.execute(
        """
        SELECT config_value
        FROM plans_plan_config
        WHERE plan_id = %s::uuid
          AND config_key = %s
        LIMIT 1
        """,
        (plan_id, config_key),
    )

    row = await cur.fetchone()
    if row is not None:
        try:
            return int(row[0])
        except (ValueError, TypeError):
            pass

    # Default rates if not configured
    defaults = {
        "voice": 50,  # 50 paise per minute
        "data": 10,  # 10 paise per MB
        "sms": 100,  # 100 paise per SMS
    }
    return defaults.get(event_type, 0)


async def _get_balance_impact(
    conn: AsyncConnection,
    subscriber_id: str | UUID,
    cdr_id: str,
) -> tuple[int, int]:
    """Get balance before/after from billing_transactions (Story 5.7).

    Queries billing_transactions for the CDR deduction transaction
    to retrieve balance impact.

    Parameters
    ----------
    conn : AsyncConnection
        Postgres connection.
    subscriber_id : str | UUID
        Subscriber UUID.
    cdr_id : str
        CDR event ID to find transaction for.

    Returns
    -------
    tuple[int, int]
        (balance_before_paise, balance_after_paise). Returns (0, 0)
        if transaction not found.
    """
    cur = await conn.execute(
        """
        SELECT balance_before_paise, balance_after_paise
        FROM billing_transactions
        WHERE subscriber_id = %s::uuid
          AND reference_type = 'cdr'
          AND reference_id = %s::uuid
          AND transaction_type = 'deduction'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (str(subscriber_id), str(cdr_id)),
    )

    row = await cur.fetchone()
    if row is None:
        return (0, 0)

    return (row[0], row[1])


async def get_subscriber_usage_profile(
    conn: AsyncConnection,
    subscriber_id: UUID,
    days: int = 30,
) -> dict:
    """Aggregate 30-day CDR usage profile for plan recommendation (Story 5.9 AC #1)."""
    start = datetime.now(UTC) - timedelta(days=days)
    cur = await conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN cdr_type = 'data' THEN volume_mb ELSE 0 END), 0)                              AS total_data_mb,
            COALESCE(SUM(CASE WHEN cdr_type = 'voice' AND NOT roaming THEN duration_seconds ELSE 0 END), 0)      AS total_voice_seconds,
            COALESCE(SUM(CASE WHEN cdr_type = 'voice' AND roaming     THEN duration_seconds ELSE 0 END), 0)      AS total_intl_seconds,
            COALESCE(SUM(CASE WHEN cdr_type = 'sms'   THEN 1 ELSE 0 END), 0)                                     AS total_sms_count,
            COALESCE(SUM(charge_paise), 0)                                                                        AS total_spend_paise
          FROM billing_cdr_events
         WHERE subscriber_id = %s::uuid
           AND start_time >= %s::timestamptz
        """,
        (str(subscriber_id), start),
    )
    row = await cur.fetchone()
    if row is None:
        return {
            "total_data_mb": 0.0,
            "total_voice_seconds": 0,
            "total_intl_seconds": 0,
            "total_sms_count": 0,
            "total_spend_paise": 0,
        }
    return {
        "total_data_mb": float(row[0]),
        "total_voice_seconds": int(row[1]),
        "total_intl_seconds": int(row[2]),
        "total_sms_count": int(row[3]),
        "total_spend_paise": int(row[4]),
    }


async def get_last_recharge_amount(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> int | None:
    """Return the amount_paise of the last completed recharge, or None (Story 5.9 AC #1)."""
    cur = await conn.execute(
        """
        SELECT amount_paise FROM recharge_orders
         WHERE subscriber_id = %s::uuid
           AND status = 'completed'
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else None


async def get_current_plan_details(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> dict | None:
    """Return the plan details from the last completed recharge, or None (Story 5.9 AC #4)."""
    cur = await conn.execute(
        """
        SELECT p.plan_name, p.data_limit_mb, p.voice_minutes, p.price_paise
          FROM recharge_orders r
          JOIN plans_plans p ON r.plan_id = p.id
         WHERE r.subscriber_id = %s::uuid
           AND r.status = 'completed'
         ORDER BY r.created_at DESC
         LIMIT 1
        """,
        (str(subscriber_id),),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "plan_name": row[0],
        "data_limit_mb": row[1],
        "voice_minutes": row[2],
        "price_paise": int(row[3]),
    }


async def get_population_usage_stats(conn: AsyncConnection) -> dict:
    """Return percentile stats from mv_usage_population_stats, or empty dict (Story 5.9 AC #1)."""
    cur = await conn.execute("SELECT * FROM mv_usage_population_stats")
    row = await cur.fetchone()
    if row is None:
        return {}
    desc = cur.description or []
    return {col.name: (float(val) if val is not None else 0.0) for col, val in zip(desc, row)}


__all__ = [
    "get_active_plan",
    "get_active_plan_data_quota",
    "get_active_subscription",
    "get_charge_breakdown",
    "get_current_plan_details",
    "get_last_recharge_amount",
    "get_msisdn_for_subscriber",
    "get_population_usage_stats",
    "get_subscriber_usage_profile",
    "get_transactions_page",
    "get_usage_for_period",
    "get_wallet_balance_from_db",
]
