"""Write CQRS commands for the recharge domain (Story 3.5).

All functions accept a psycopg ``AsyncConnection`` (from ``db.transaction()``).
Raw SQL via psycopg3; no ORM.

The recharge endpoint runs as a single Postgres transaction that:
1. Creates the recharge_order (idempotent via idempotency_key UNIQUE)
2. Resolves plan price and validates payment method ownership
3. Simulates payment success (no real gateway)
4. Updates wallet balance (UPSERT billing_wallet_balances)
5. Appends transaction record (billing_transactions)
6. Deactivates prior subscription and creates new one (plans_subscriptions)
7. Creates receipt record (recharge_receipts)

Idempotency: If the same idempotency_key is retried, we return the original
completed order result without re-crediting (AC #6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def create_recharge_order(
    conn: AsyncConnection,
    subscriber_id: UUID,
    plan_id: UUID,
    payment_method_id: UUID,
    idempotency_key: str,
) -> dict | None:
    """Create a recharge order with idempotency guard.

    Returns ``None`` if the order already exists (idempotent retry).
    Returns the created order row as dict otherwise.

    The ``ON CONFLICT (idempotency_key) DO NOTHING`` ensures that if a
    duplicate idempotency_key is submitted, we return None — the caller
    then fetches the original order to return its result (AC #6).
    """
    cur = await conn.execute(
        """
        INSERT INTO recharge_orders (
            subscriber_id, plan_id, payment_method_id, idempotency_key,
            amount_paise, status
        )
        SELECT $1, $2, $3, $4, price_paise, 'pending'
        FROM plans_plans
        WHERE id = $2 AND is_active = true
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id, subscriber_id, plan_id, amount_paise, status, created_at
        """,
        (subscriber_id, plan_id, payment_method_id, idempotency_key),
    )
    row = await cur.fetchone()
    if row is None:
        return None

    return {
        "id": row[0],
        "subscriber_id": row[1],
        "plan_id": row[2],
        "amount_paise": row[3],
        "status": row[4],
        "created_at": row[5],
    }


async def get_payment_method_owner(
    conn: AsyncConnection,
    payment_method_id: UUID,
) -> UUID | None:
    """Return the subscriber_id who owns this payment method.

    Returns ``None`` if the payment method doesn't exist.
    Used to validate that the caller can only use their own payment methods.
    """
    cur = await conn.execute(
        """
        SELECT subscriber_id
        FROM recharge_payment_methods
        WHERE id = $1 AND is_active = true
        """,
        (payment_method_id,),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def get_subscriber_msisdn(
    conn: AsyncConnection,
    subscriber_id: UUID,
) -> str | None:
    """Return the MSISDN for a subscriber (for Valkey balance operations).

    Returns ``None`` if subscriber doesn't exist.
    """
    cur = await conn.execute(
        """
        SELECT msisdn
        FROM identity_subscribers
        WHERE id = $1
        """,
        (subscriber_id,),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def complete_recharge_transaction(
    conn: AsyncConnection,
    order_id: UUID,
    subscriber_id: UUID,
    amount_paise: int,
) -> dict:
    """Complete the recharge: update balance, transaction, subscription, receipt.

    This runs within a single transaction and performs:
    1. Mark recharge_order as completed
    2. UPSERT wallet balance (credit amount)
    3. Append billing_transactions record
    4. Deactivate prior subscriptions
    5. Insert new active subscription
    6. Create receipt record

    Returns a dict with:
    - transaction_id (order_id)
    - new_balance_paise
    - plan_activation_timestamp
    - msisdn (for Valkey INCRBY)
    """
    # Get MSISDN for Valkey operation
    msisdn = await get_subscriber_msisdn(conn, subscriber_id)
    if msisdn is None:
        raise ValueError("Subscriber not found")

    # Get plan details for subscription
    cur = await conn.execute(
        """
        SELECT price_paise, validity_days
        FROM plans_plans
        WHERE id = (SELECT plan_id FROM recharge_orders WHERE id = $1)
        """,
        (order_id,),
    )
    plan_row = await cur.fetchone()
    if plan_row is None:
        raise ValueError("Plan not found for order")

    validity_days = plan_row[1]

    # 1. Mark order as completed
    await conn.execute(
        """
        UPDATE recharge_orders
        SET status = 'completed', completed_at = NOW()
        WHERE id = $1
        """,
        (order_id,),
    )

    # 2. UPSERT wallet balance (credit amount)
    cur = await conn.execute(
        """
        INSERT INTO billing_wallet_balances (subscriber_id, msisdn, balance_paise, last_recharge_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (subscriber_id)
        DO UPDATE SET
            balance_paise = billing_wallet_balances.balance_paise + $3,
            last_recharge_at = NOW()
        RETURNING balance_paise
        """,
        (subscriber_id, msisdn, amount_paise),
    )
    balance_row = await cur.fetchone()
    new_balance_paise = balance_row[0]

    # 3. Append billing_transactions record
    await conn.execute(
        """
        INSERT INTO billing_transactions (
            subscriber_id, transaction_type, amount_paise,
            reference_type, reference_id, description,
            balance_before_paise, balance_after_paise
        )
        VALUES (
            $1, 'recharge', $2,
            'recharge', $3, 'Plan recharge',
            $4, $5
        )
        """,
        (subscriber_id, amount_paise, order_id, new_balance_paise - amount_paise, new_balance_paise),
    )

    # 4. Deactivate prior subscriptions
    await conn.execute(
        """
        UPDATE plans_subscriptions
        SET status = 'inactive', end_date = NOW()
        WHERE subscriber_id = $1 AND status = 'active'
        """,
        (subscriber_id,),
    )

    # 5. Insert new active subscription
    cur = await conn.execute(
        """
        INSERT INTO plans_subscriptions (
            subscriber_id, plan_id, start_date, end_date, status
        )
        SELECT $1, plan_id, NOW(), NOW() + (validity_days || ' days')::interval, 'active'
        FROM recharge_orders
        JOIN plans_plans ON plans_plans.id = recharge_orders.plan_id
        WHERE recharge_orders.id = $2
        RETURNING start_date
        """,
        (subscriber_id, order_id),
    )
    subscription_row = await cur.fetchone()
    plan_activation_timestamp = subscription_row[0]

    # 6. Create receipt record (Story 3.6 will generate the PDF)
    receipt_number = f"RCP-{order_id}"
    await conn.execute(
        """
        INSERT INTO recharge_receipts (recharge_order_id, receipt_number)
        VALUES ($1, $2)
        """,
        (order_id, receipt_number),
    )

    return {
        "transaction_id": order_id,
        "new_balance_paise": new_balance_paise,
        "plan_activation_timestamp": plan_activation_timestamp,
        "msisdn": msisdn,
    }


async def get_completed_recharge_result(
    conn: AsyncConnection,
    idempotency_key: str,
) -> dict | None:
    """Fetch the original completed recharge result for idempotent retry.

    Returns ``None`` if no completed order exists for this idempotency_key.
    Returns the original order details otherwise.

    Used when a duplicate idempotency_key is submitted — we return the
    original completed result instead of processing a new recharge (AC #6).
    """
    cur = await conn.execute(
        """
        SELECT ro.id, ro.subscriber_id, ro.amount_paise, ro.completed_at,
               wb.balance_paise, ps.start_date, s.msisdn
        FROM recharge_orders ro
        JOIN billing_wallet_balances wb ON wb.subscriber_id = ro.subscriber_id
        JOIN plans_subscriptions ps ON ps.subscriber_id = ro.subscriber_id AND ps.status = 'active'
        JOIN identity_subscribers s ON s.id = ro.subscriber_id
        WHERE ro.idempotency_key = $1 AND ro.status = 'completed'
        ORDER BY ro.completed_at DESC
        LIMIT 1
        """,
        (idempotency_key,),
    )
    row = await cur.fetchone()
    if row is None:
        return None

    return {
        "transaction_id": row[0],
        "subscriber_id": row[1],
        "amount_paise": row[2],
        "completed_at": row[3],
        "new_balance_paise": row[4],
        "plan_activation_timestamp": row[5],
        "msisdn": row[6],
    }


__all__ = [
    "complete_recharge_transaction",
    "create_recharge_order",
    "get_completed_recharge_result",
    "get_payment_method_owner",
]
