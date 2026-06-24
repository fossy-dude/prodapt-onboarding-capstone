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


async def get_receipt_data(
    conn: AsyncConnection,
    transaction_id: str,
) -> dict | None:
    """Return data needed to render a PDF receipt for a completed recharge order.

    Joins recharge_orders → plans_plans, identity_subscribers, recharge_payment_methods,
    and recharge_receipts. Returns None when the order does not exist or is not completed.
    """
    cur = await conn.execute(
        """
        SELECT
            ro.id                  AS transaction_id,
            ro.subscriber_id       AS subscriber_id,
            ro.amount_paise        AS amount_paise,
            ro.created_at          AS transaction_date,
            pp.plan_name           AS plan_name,
            ist.subscriber_name    AS subscriber_name_encrypted,
            ist.msisdn             AS msisdn,
            rpm.method_type        AS method_type,
            rpm.last_four          AS last_four,
            rr.receipt_number      AS receipt_number
          FROM recharge_orders ro
          JOIN plans_plans pp               ON pp.id = ro.plan_id
          JOIN identity_subscribers ist     ON ist.id = ro.subscriber_id
          LEFT JOIN recharge_payment_methods rpm ON rpm.id = ro.payment_method_id
          LEFT JOIN recharge_receipts rr    ON rr.recharge_order_id = ro.id
         WHERE ro.id = %s::uuid
           AND ro.status = 'completed'
        """,
        (transaction_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "transaction_id": str(row[0]),
        "subscriber_id": str(row[1]),
        "amount_paise": row[2],
        "transaction_date": row[3],
        "plan_name": row[4],
        "subscriber_name_encrypted": row[5],
        "msisdn": row[6],
        "method_type": row[7],
        "last_four": row[8],
        "receipt_number": row[9],
    }


async def get_failed_orders(
    conn: AsyncConnection,
    subscriber_id: str,
) -> list[dict]:
    """Return failed recharge orders for refund-eligible view (Story 3.7).

    Reads recharge_orders WHERE status='failed' — NOT billing_transactions,
    which has no status column and records no failed payments.
    failure_reason is NULL until a real failure path exists (FR-14 simulated
    payment always succeeds in the current MVP).
    """
    cur = await conn.execute(
        """
        SELECT
            ro.id               AS transaction_id,
            pp.plan_name        AS plan_attempted,
            ro.amount_paise     AS amount_paise,
            ro.failure_reason   AS failure_reason,
            ro.created_at       AS created_at
          FROM recharge_orders ro
          JOIN plans_plans pp ON pp.id = ro.plan_id
         WHERE ro.subscriber_id = %s::uuid
           AND ro.status = 'failed'
         ORDER BY ro.created_at DESC
        """,
        (subscriber_id,),
    )
    rows = await cur.fetchall()
    return [
        {
            "transaction_id": str(row[0]),
            "plan_attempted": row[1],
            "amount_paise": row[2],
            "failure_reason": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


__all__ = ["get_active_plans", "get_failed_orders", "get_receipt_data"]
