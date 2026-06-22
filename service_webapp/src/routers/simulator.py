"""Simulator developer-tool router (FR-68 to FR-70; architecture §1.12.1).

Story 1.7 adds a state-advance endpoint so developers can drive
``ops_order_fulfilment`` through the activation state machine without
wiring real KYC or operator backends.

State machine (forward-only):
    CREATED → KYC_PENDING → KYC_VERIFIED → ACTIVATED
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError, NotFoundError
from core.responses import success_envelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])

_STATE_MACHINE: dict[str, str] = {
    "CREATED": "KYC_PENDING",
    "KYC_PENDING": "KYC_VERIFIED",
    "KYC_VERIFIED": "ACTIVATED",
}


def _db(request: Request):
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _validate_order_id(order_id: str) -> None:
    """Reject non-UUID ``order_id`` path params as 404 before they reach SQL.

    A malformed value would otherwise hit the ``%s::uuid`` cast and raise a
    psycopg ``DataError`` → unhandled 500.
    """
    try:
        uuid.UUID(order_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError("Order not found.") from exc


@router.get("/orders", status_code=200)
async def list_orders(
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """List recent ``ops_order_fulfilment`` rows for the simulator dev tool (AC #6).

    Returns up to 100 most-recent orders with their id + current state so the dev
    tool can populate its table without a separate seeding step. No MSISDN is
    returned (PII hygiene — the dev tool does not need raw PII to advance state).
    """
    db = _db(request)
    async with db.transaction() as conn:
        cur = await conn.execute(
            """
            SELECT id::text, fulfilment_status, created_at
            FROM ops_order_fulfilment
            ORDER BY created_at DESC
            LIMIT 100
            """,
        )
        rows = await cur.fetchall()
    orders = [
        {
            "order_id": row[0],
            "current_status": row[1],
            "created_at": row[2].isoformat() if row[2] is not None else None,
        }
        for row in rows
    ]
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"orders": orders},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


@router.post("/orders/{order_id}/advance", status_code=200)
async def advance_order_state(
    order_id: str,
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """Advance ``order_id`` one step through the activation state machine (AC #6).

    Only forward transitions are permitted. Advancing from ``ACTIVATED`` (terminal)
    returns HTTP 400 (``ILLEGAL_TRANSITION``); a row in an unknown state returns
    HTTP 409 (``UNKNOWN_STATE``). Unknown orders return HTTP 404.

    The row is locked ``FOR UPDATE`` and the UPDATE carries an optimistic
    ``fulfilment_status = %s`` guard so two concurrent advances cannot double-step
    or clobber a writer racing between the SELECT and UPDATE.
    """
    _validate_order_id(order_id)
    db = _db(request)
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT fulfilment_status FROM ops_order_fulfilment WHERE id = %s::uuid FOR UPDATE",
            (order_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Order not found.")
        current_status = row[0] or ""
        next_status = _STATE_MACHINE.get(current_status)
        if next_status is None:
            if current_status == "ACTIVATED":
                err = DomainError("Order is already in terminal state 'ACTIVATED'.")
                err.code = "ILLEGAL_TRANSITION"
                err.http_status = 400
            else:
                err = DomainError(f"Order is in an unknown state '{current_status}'; cannot advance.")
                err.code = "UNKNOWN_STATE"
                err.http_status = 409
            raise err
        await conn.execute(
            """
            UPDATE ops_order_fulfilment
               SET fulfilment_status = %s,
                   modified_at = NOW()
             WHERE id = %s::uuid AND fulfilment_status = %s
            """,
            (next_status, order_id, current_status),
        )
    logger.info("simulator advance order_id=%s %s→%s", order_id, current_status, next_status)
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"order_id": order_id, "previous_status": current_status, "status": next_status},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


__all__ = ["router"]
