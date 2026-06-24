"""Read-only DB queries for the plans domain (Story 4.4 USSD).

All functions accept a psycopg ``AsyncConnection``.
Raw SQL via psycopg3; no ORM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def get_active_subscription(conn: AsyncConnection, subscriber_id: str) -> dict | None:
    """Return active subscription with plan allowances and expiry, or ``None``."""
    cur = await conn.execute(
        """
        SELECT
            pp.plan_name,
            ps.end_date,
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
        (subscriber_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "plan_name": row[0],
        "end_date": row[1],
        "data_limit_mb": row[2],
        "voice_minutes": row[3],
        "sms_count": row[4],
    }


async def get_available_plans(conn: AsyncConnection, limit: int = 5) -> list[dict]:
    """Return up to ``limit`` active plans ordered by price ascending."""
    cur = await conn.execute(
        """
        SELECT id, plan_name, price_paise, data_limit_mb, voice_minutes, sms_count
          FROM plans_plans
         WHERE is_active = TRUE
         ORDER BY price_paise ASC
         LIMIT %s
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    return [
        {
            "id": str(row[0]),
            "plan_name": row[1],
            "price_paise": row[2],
            "data_limit_mb": row[3],
            "voice_minutes": row[4],
            "sms_count": row[5],
        }
        for row in rows
    ]


__all__ = ["get_active_subscription", "get_available_plans"]
