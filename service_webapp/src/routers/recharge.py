"""Recharge / plan-catalogue endpoints for authenticated subscribers (Stories 3.4, 3.5).

GET /api/v1/plans — browse all active plans (FR-12) [Story 3.4]
POST /api/v1/subscriber/recharge — complete a recharge with idempotency (FR-13, FR-14, FR-16) [Story 3.5]

The catalogue is shared data (every subscriber sees the same plans), so it is
guarded by ``require_role("subscriber")`` only — there is no owner assertion.
Money is integer paise; ``data_limit_mb`` is converted to ``data_gb`` here at the
presentation boundary.
"""

from __future__ import annotations

import logging
import zoneinfo
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import require_role
from core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError, UnauthenticatedError
from core.responses import success_envelope
from core.security import decrypt_pii
from db.recharge.commands import (
    complete_recharge_transaction,
    create_recharge_order,
    get_completed_recharge_result,
    get_payment_method_owner,
)
from db.recharge.queries import get_active_plans, get_receipt_data
from models.plan import PlanCatalogueItem
from models.recharge import RechargeRequest, RechargeResponse
from receipts.render import render_receipt_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["recharge"])


def _db(request: Request):
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


def _require_sub(jwt_payload: dict) -> str:
    """Extract the subscriber UUID (JWT ``sub``); 401 if the claim is absent.

    ``require_role`` validates ``cognito:groups`` but never asserts ``sub`` is
    present, so a valid token lacking ``sub`` would otherwise raise a raw
    ``KeyError`` → HTTP 500. Surface it as a clean 401 instead.
    """
    sub = jwt_payload.get("sub")
    if not sub:
        raise UnauthenticatedError("Access token is missing the 'sub' claim.")
    return str(sub)


def _cache(request: Request):
    """Resolve the Valkey cache adapter from app state."""
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        err = DomainError("Cache adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return cache


@router.get("/plans", status_code=200)
async def list_plans(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return all active plans for the catalogue (AC #3).

    Shared catalogue data — no owner assertion (every subscriber sees the same
    plans). ``data_gb = round(data_limit_mb / 1024, 2)``; ``None`` means
    unlimited. ``plan_type`` is ``None`` (V1 has no such column).
    """
    db = _db(request)

    async with db.transaction() as conn:
        rows = await get_active_plans(conn)

    def _data_gb(data_limit_mb: int | None) -> float | None:
        return round(data_limit_mb / 1024, 2) if data_limit_mb is not None else None

    items = [
        PlanCatalogueItem(
            id=row["id"],
            name=row["plan_name"],
            data_gb=_data_gb(row["data_limit_mb"]),
            voice_minutes=row["voice_minutes"],
            sms_count=row["sms_count"],
            validity_days=row["validity_days"],
            price_paise=row["price_paise"],
            plan_type=None,
        )
        for row in rows
    ]

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            [item.model_dump(mode="json") for item in items],
            trace_id=_trace_id(request),
        ),
    )


@router.post("/subscriber/recharge", status_code=200)
async def create_recharge(
    request: Request,
    payload: RechargeRequest,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Complete a recharge with idempotency (AC #2, #3, #4, #5, #6).

    Flow:
    1. Validate idempotency_key and resolve plan/payment_method
    2. Check if order already exists (idempotent retry)
    3. Validate payment method ownership
    4. Create order in pending status
    5. Complete transaction: credit balance, update subscription, create receipt
    6. Credit Valkey balance (authoritative for reads)
    7. Return transaction result

    Idempotency: If the same idempotency_key is retried, return the original
    completed order result without re-crediting (AC #6).

    Security: Payment method token is resolved server-side; request only
    contains payment_method_id UUID (FR-64).
    """
    db = _db(request)
    cache = _cache(request)
    subscriber_id = _require_sub(jwt_payload)

    # Extract request parameters
    plan_id = payload.plan_id
    payment_method_id = payload.payment_method_id
    idempotency_key = payload.idempotency_key

    async with db.transaction() as conn:
        # Check for existing completed order (idempotent retry)
        existing = await get_completed_recharge_result(conn, idempotency_key)
        if existing is not None:
            # Idempotent retry: return original result without re-crediting
            logger.info(
                "Idempotent recharge: subscriber_id=%s idempotency_key=%s transaction_id=%s",
                subscriber_id,
                idempotency_key,
                existing["transaction_id"],
            )

            response_data = RechargeResponse(
                transaction_id=UUID(existing["transaction_id"]),
                new_balance_paise=existing["new_balance_paise"],
                plan_activation_timestamp=existing["plan_activation_timestamp"],
                receipt_url=f"/api/v1/subscriber/receipts/{existing['transaction_id']}",
            )

            return JSONResponse(
                status_code=200,
                content=success_envelope(
                    response_data.model_dump(mode="json"),
                    trace_id=_trace_id(request),
                ),
            )

        # Validate payment method ownership
        owner_id = await get_payment_method_owner(conn, payment_method_id)
        if owner_id is None:
            raise NotFoundError("Payment method not found.")
        if owner_id != subscriber_id:
            raise ForbiddenError("Payment method does not belong to this subscriber.")

        # Create recharge order (idempotent via UNIQUE constraint)
        order = await create_recharge_order(
            conn,
            subscriber_id=subscriber_id,
            plan_id=plan_id,
            payment_method_id=payment_method_id,
            idempotency_key=idempotency_key,
        )

        if order is None:
            # Race condition: another request created the order between our check and now
            # Fetch and return the completed result
            existing = await get_completed_recharge_result(conn, idempotency_key)
            if existing is not None:
                response_data = RechargeResponse(
                    transaction_id=UUID(existing["transaction_id"]),
                    new_balance_paise=existing["new_balance_paise"],
                    plan_activation_timestamp=existing["plan_activation_timestamp"],
                    receipt_url=f"/api/v1/subscriber/receipts/{existing['transaction_id']}",
                )

                return JSONResponse(
                    status_code=200,
                    content=success_envelope(
                        response_data.model_dump(mode="json"),
                        trace_id=_trace_id(request),
                    ),
                )

            raise ConflictError("Recharge order already exists with this idempotency key.")

        # Complete the transaction
        result = await complete_recharge_transaction(
            conn,
            order_id=order["id"],
            subscriber_id=subscriber_id,
            amount_paise=order["amount_paise"],
        )

    # After commit: credit Valkey balance (authoritative for reads)
    await cache.incr_balance(result["msisdn"], order["amount_paise"])

    # Set last_recharge_at timestamp for analytics
    await cache.set_str(f"last_recharge_at:{result['msisdn']}", _trace_id(request), ex=0)

    logger.info(
        "Recharge completed: subscriber_id=%s transaction_id=%s amount_paise=%s new_balance=%s",
        subscriber_id,
        result["transaction_id"],
        order["amount_paise"],
        result["new_balance_paise"],
    )

    response_data = RechargeResponse(
        transaction_id=result["transaction_id"],
        new_balance_paise=result["new_balance_paise"],
        plan_activation_timestamp=result["plan_activation_timestamp"],
        receipt_url=f"/api/v1/subscriber/receipts/{result['transaction_id']}",
    )

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            response_data.model_dump(mode="json"),
            trace_id=_trace_id(request),
        ),
    )


@router.get("/subscriber/receipts/{transaction_id}", status_code=200)
async def get_receipt(
    transaction_id: str,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
):
    """Generate and stream a PDF receipt for a completed recharge (AC #1, #4).

    Owner assertion: recharge_orders.subscriber_id == jwt.sub.
    PDF is generated on-demand via WeasyPrint (no S3 in MVP; s3_key stays null).
    PII: subscriber_name is decrypted (AES-256-GCM); MSISDN masked to last-4.
    No card numbers / full PAN in output (FR-64).
    """
    db = _db(request)
    subscriber_id = _require_sub(jwt_payload)

    async with db.transaction() as conn:
        row = await get_receipt_data(conn, transaction_id)

    if row is None:
        raise NotFoundError("Receipt not found or order is not completed.")

    if row["subscriber_id"] != subscriber_id:
        raise ForbiddenError("Receipt does not belong to this subscriber.")

    # PII: decrypt name, mask MSISDN to last-4 only
    subscriber_name = decrypt_pii(row["subscriber_name_encrypted"])
    msisdn_last4 = row["msisdn"][-4:]

    # Format transaction date as DD MMM YYYY HH:MM IST
    txn_dt = row["transaction_date"]
    if txn_dt is not None:
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        txn_dt_ist = txn_dt.astimezone(ist)
        date_str = txn_dt_ist.strftime("%d %b %Y %H:%M IST")
    else:
        date_str = "—"

    amount_inr = f"{row['amount_paise'] / 100:.2f}"

    pdf_bytes = render_receipt_pdf(
        transaction_id=transaction_id,
        subscriber_name=subscriber_name,
        msisdn_last4=msisdn_last4,
        transaction_date=date_str,
        plan_name=row["plan_name"],
        amount_inr=amount_inr,
        method_type=row["method_type"],
        last_four=row["last_four"],
        receipt_number=row["receipt_number"],
    )

    headers = {
        "Content-Disposition": f'attachment; filename="receipt_{transaction_id}.pdf"',
        "Content-Length": str(len(pdf_bytes)),
    }
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers=headers,
    )
