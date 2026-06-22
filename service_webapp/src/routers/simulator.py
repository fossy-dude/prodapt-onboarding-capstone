"""Simulator developer-tool router (FR-68 to FR-70; architecture §1.12.1).

Story 1.7 adds a state-advance endpoint so developers can drive
``ops_order_fulfilment`` through the activation state machine without
wiring real KYC or operator backends.

State machine (forward-only):
    CREATED → KYC_PENDING → KYC_VERIFIED → ACTIVATED
"""

from __future__ import annotations

import logging

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


@router.post("/orders/{order_id}/advance", status_code=200)
async def advance_order_state(
    order_id: str,
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """Advance ``order_id`` one step through the activation state machine (AC #6).

    Only forward transitions are permitted. Advancing from ``ACTIVATED`` (terminal)
    returns HTTP 400. Unknown orders return HTTP 404.
    """
    db = _db(request)
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT fulfilment_status FROM ops_order_fulfilment WHERE id = %s::uuid",
            (order_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Order not found.")
        current_status: str = row[0]
        next_status = _STATE_MACHINE.get(current_status)
        if next_status is None:
            err = DomainError(f"Order is already in terminal state '{current_status}'.")
            err.code = "ILLEGAL_TRANSITION"
            err.http_status = 400
            raise err
        await conn.execute(
            """
            UPDATE ops_order_fulfilment
               SET fulfilment_status = %s,
                   modified_at = NOW()
             WHERE id = %s::uuid
            """,
            (next_status, order_id),
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
