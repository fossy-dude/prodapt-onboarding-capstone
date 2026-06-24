"""Read-only CQRS queries for billing domain (Story 3.2; architecture §1.11.2 CQRS).

All functions accept a psycopg ``AsyncConnection`` (from ``db.transaction()``).
Raw SQL via psycopg3; no ORM.

Usage data: sourced from ``billing_cdr_events`` (written by Story 2.2).
No ``billing_usage_summary`` view exists in V1 migrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
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
    data_mb_used = float(usage_row[0]) if usage_row[0] is not None else 0.0

    return (data_mb_used, data_limit_mb)


__all__ = [
    "get_active_plan",
    "get_active_plan_data_quota",
    "get_active_subscription",
    "get_msisdn_for_subscriber",
    "get_transactions_page",
    "get_usage_for_period",
    "get_wallet_balance_from_db",
]
