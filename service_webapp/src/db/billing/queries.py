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
         ORDER BY ps.start_date DESC
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


__all__ = [
    "get_active_subscription",
    "get_msisdn_for_subscriber",
    "get_usage_for_period",
    "get_wallet_balance_from_db",
]
