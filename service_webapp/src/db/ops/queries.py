"""Read-only DB queries for the ops domain (Story 7.2).

All functions accept a psycopg ``AsyncConnection``.
Raw SQL via psycopg3; no ORM.
Per CQRS ARCH-4, this module contains SELECT-only queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


__all__ = ["get_order_fulfilment_counts", "get_orders_by_status", "get_plan_stock_counts"]
