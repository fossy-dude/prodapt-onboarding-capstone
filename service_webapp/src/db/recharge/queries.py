"""Read-only CQRS queries for the recharge / plan-catalogue domain (Story 3.4).

All functions accept a psycopg ``AsyncConnection`` (from ``db.transaction()``).
Raw SQL via psycopg3; no ORM.

The catalogue exposes only active plans (``plans_plans.is_active = true``); the
``data_limit_mb`` column is converted to ``data_gb`` by the caller (presentation
boundary). There is no ``plan_type`` column in V1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def get_active_plans(conn: AsyncConnection) -> list[dict]:
    """Return all active plans for the catalogue (FR-12).

    Rows are returned raw (``data_limit_mb`` etc.); the router derives
    ``data_gb`` and sets ``plan_type`` to ``None`` (no such column in V1).
    """
    cur = await conn.execute(
        """
        SELECT id, plan_name, price_paise, validity_days,
               data_limit_mb, voice_minutes, sms_count
          FROM plans_plans
         WHERE is_active = true
         ORDER BY price_paise ASC, validity_days ASC
        """,
        (),
    )
    rows = await cur.fetchall()
    return [
        {
            "id": row[0],
            "plan_name": row[1],
            "price_paise": row[2],
            "validity_days": row[3],
            "data_limit_mb": row[4],
            "voice_minutes": row[5],
            "sms_count": row[6],
        }
        for row in rows
    ]


__all__ = ["get_active_plans"]
