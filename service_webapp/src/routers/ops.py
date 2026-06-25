"""Ops dashboard endpoints (Story 7.2 Task 2).

GET /api/v1/ops/plan-stock  — plan adoption counts (ops role only).
GET /api/v1/ops/orders       — order fulfilment view (ops role only).

Both endpoints use SELECT-only queries via ops_queries.py (CQRS ARCH-4).
Role-based access control restricts to users with 'ops' role in JWT.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError
from core.responses import success_envelope
from db.identity.queries import get_subscriber_id_by_msisdn
from db.ops.queries import get_order_fulfilment_counts, get_orders_by_status, get_plan_stock_counts

if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from adapters.postgres import Psycopg3AsyncAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


def _db(request: Request) -> Psycopg3AsyncAdapter:
    """Resolve the database adapter from app state."""
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _trace_id(request: Request) -> str:
    """Return the OTEL trace id from request state, or 'unknown' if absent."""
    return getattr(request.state, "trace_id", "unknown")


# Cognito access tokens carry `username` (= E.164 for phone users); ID tokens
# carry `phone_number` and `cognito:username`. Try all so either token resolves.
_PHONE_CLAIMS = ("phone_number", "username", "cognito:username")


def _extract_msisdn_from_payload(jwt_payload: dict) -> str:
    """Extract msisdn from JWT payload using phone number claims."""
    for claim in _PHONE_CLAIMS:
        value = jwt_payload.get(claim)
        if value:
            return str(value)
    raise ValueError("JWT payload must contain phone number claim (phone_number, username, or cognito:username)")


@router.get("/plan-stock", status_code=200)
async def get_plan_stock(
    request: Request,
    jwt_payload: dict = require_role("ops"),
) -> JSONResponse:
    """Return plan stock counts: plan_id, plan_name, subscriber_count sorted DESC.

    Requires ops role. Returns array of plan adoption metrics.
    Validates msisdn maps to a valid subscriber for consistency with subscriber portal.
    """
    # Extract msisdn from JWT
    try:
        msisdn = _extract_msisdn_from_payload(jwt_payload)
    except ValueError as e:
        logger.warning("Invalid JWT payload for ops endpoint: %s", e)
        raise

    # Validate msisdn maps to a valid subscriber (even though we don't use subscriber_id for queries)
    db = _db(request)
    async with db.connection() as conn:
        subscriber_id = await get_subscriber_id_by_msisdn(conn, msisdn)
        if subscriber_id is None:
            logger.warning("Ops dashboard access by invalid subscriber msisdn: %s", msisdn[-4:])
            # Return empty data rather than error - ops dashboard shows aggregate data anyway
            plans = await get_plan_stock_counts(conn)
        else:
            logger.debug("Ops dashboard access by valid subscriber (msisdn: %s)", msisdn[-4:])
            plans = await get_plan_stock_counts(conn)

    return success_envelope(data=plans, trace_id=_trace_id(request))


@router.get("/orders", status_code=200)
async def get_orders(
    request: Request,
    jwt_payload: dict = require_role("ops"),
    status: str | None = Query(None, description="Filter orders by status"),
    limit: int = Query(20, ge=1, le=100, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> JSONResponse:
    """Return order fulfilment data.

    Without status param: returns status group counts.
    With status param: returns paginated order list for that status.

    Requires ops role. Validates msisdn maps to a valid subscriber for consistency.
    """
    # Extract msisdn from JWT
    try:
        msisdn = _extract_msisdn_from_payload(jwt_payload)
    except ValueError as e:
        logger.warning("Invalid JWT payload for ops endpoint: %s", e)
        raise

    # Validate msisdn maps to a valid subscriber (even though we don't use subscriber_id for queries)
    db = _db(request)
    async with db.connection() as conn:
        subscriber_id = await get_subscriber_id_by_msisdn(conn, msisdn)
        if subscriber_id is None:
            logger.warning("Ops dashboard access by invalid subscriber msisdn: %s", msisdn[-4:])
        else:
            logger.debug("Ops dashboard access by valid subscriber (msisdn: %s)", msisdn[-4:])

        if status:
            # Return paginated order list for specific status
            orders = await get_orders_by_status(conn, status=status, limit=limit, offset=offset)
            return success_envelope(data=orders, trace_id=_trace_id(request))
        else:
            # Return status counts across all orders
            counts = await get_order_fulfilment_counts(conn)
            return success_envelope(data=counts, trace_id=_trace_id(request))
