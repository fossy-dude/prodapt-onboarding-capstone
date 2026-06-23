"""Balance and usage endpoints for authenticated subscribers (Story 3.2).

GET /api/v1/subscriber/balance  — current wallet balance (Valkey-authoritative).
GET /api/v1/subscriber/usage    — per-type CDR usage vs plan allowances.

Both endpoints enforce subscriber ownership via ``_require_sub`` (deferred-work D3;
``require_role`` validates groups but does not assert JWT ``sub``).
MSISDN is always masked to last-4 in responses and logs (PII hygiene §1.11.6).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError, NotFoundError, UnauthenticatedError
from core.responses import success_envelope
from core.security import mask_msisdn
from db.billing.queries import (
    get_active_plan,
    get_active_subscription,
    get_transactions_page,
    get_usage_for_period,
    get_wallet_balance_from_db,
)
from models.balance import UsageAllowance, UsagePeriod, UsageResponse, WalletBalanceResponse
from models.plan import ActivePlanResponse, PlanQuotas
from models.transaction import TransactionItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subscriber", tags=["balance"])


def _require_sub(jwt_payload: dict) -> str:
    """Extract the subscriber UUID (JWT ``sub``); 401 if the claim is absent."""
    sub = jwt_payload.get("sub")
    if not sub:
        raise UnauthenticatedError("Access token is missing the 'sub' claim.")
    return str(sub)


def _cache(request: Request):
    """Resolve the cache adapter from app state."""
    cache = getattr(request.app.state, "cache_adapter", None)
    if cache is None:
        err = DomainError("Cache adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return cache


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


@router.get("/balance", status_code=200)
async def get_balance(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return the subscriber's current wallet balance (AC #1, #2, #3).

    Reads from Valkey ``balance:{msisdn}`` (authoritative, ARCH-6). On cache miss
    falls back to ``billing_wallet_balances.balance_paise``. Owner assertion
    (``subscriber_id == jwt.sub``) is enforced via ``_require_sub``.
    """
    sub_id = _require_sub(jwt_payload)
    cache = _cache(request)
    db = _db(request)

    async with db.transaction() as conn:
        wallet = await get_wallet_balance_from_db(conn, UUID(sub_id))

    if wallet is None:
        raise NotFoundError("Subscriber wallet not found.")

    msisdn: str = wallet["msisdn"]

    balance_paise = await cache.get_balance(msisdn)
    if balance_paise is None:
        balance_paise = wallet["balance_paise"]
        logger.debug("balance cache-miss sub=%s msisdn=%s", sub_id, mask_msisdn(msisdn))

    last_updated = wallet["last_deduction_at"] or wallet["last_recharge_at"]

    resp = WalletBalanceResponse(
        subscriber_id=UUID(sub_id),
        msisdn_masked=mask_msisdn(msisdn),
        balance_paise=balance_paise,
        balance_inr=f"₹{balance_paise / 100:.2f}",
        last_updated_at=last_updated,
    )
    return JSONResponse(
        status_code=200,
        content=success_envelope(resp.model_dump(mode="json"), trace_id=_trace_id(request)),
    )


@router.get("/usage", status_code=200)
async def get_usage(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return per-type CDR usage vs plan allowances for the active plan window (AC #4, #5).

    Usage is aggregated from ``billing_cdr_events`` (status='charged') for the
    active ``plans_subscriptions`` window. Allowances come from ``plans_plans``.
    Null/0 quota → unlimited=True per PRD FR-10.
    """
    sub_id = _require_sub(jwt_payload)
    db = _db(request)

    async with db.transaction() as conn:
        sub = await get_active_subscription(conn, UUID(sub_id))
        if sub is None:
            raise NotFoundError("No active plan subscription found.")

        usage = await get_usage_for_period(
            conn,
            UUID(sub_id),
            sub["start_date"],
            sub["end_date"],
        )

    def _allowance(used: float, limit: int | None) -> UsageAllowance:
        unlimited = limit is None or limit == 0
        return UsageAllowance(
            used=used,
            allowance=None if unlimited else float(limit),
            unlimited=unlimited,
        )

    data_mb = usage["data_mb_used"]
    resp = UsageResponse(
        subscriber_id=UUID(sub_id),
        plan_period=UsagePeriod(start=sub["start_date"], end=sub["end_date"]),
        voice_minutes=_allowance(usage["voice_minutes_used"], sub["voice_minutes_allowance"]),
        data_mb=data_mb,
        data_gb=round(data_mb / 1024, 3),
        data=_allowance(data_mb, sub["data_limit_mb_allowance"]),
        sms=_allowance(float(usage["sms_count_used"]), sub["sms_count_allowance"]),
        roaming_mb=_allowance(usage["roaming_mb_used"], None),
    )
    return JSONResponse(
        status_code=200,
        content=success_envelope(resp.model_dump(mode="json"), trace_id=_trace_id(request)),
    )


@router.get("/transactions", status_code=200)
async def get_transactions(
    request: Request,
    cursor: UUID | None = Query(default=None, description="Keyset cursor (last id of the prior page)."),
    page_size: int = Query(default=20, ge=1, le=100),
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return a paginated, immutable ledger of the subscriber's transactions (AC #1-#5).

    Rows come from the append-only ``billing_transactions`` table, newest first,
    keyset-paginated by ``id`` (UUIDv7 time-monotonic). ``cdr_reference`` is
    derived from ``reference_id`` where ``reference_type = 'cdr'`` (no such
    column exists). ``transaction_type`` is the raw stored writer value.

    Owner assertion: ``subscriber_id`` is always the JWT ``sub`` (``_require_sub``),
    so a subscriber can only ever read their own ledger.
    """
    sub_id = _require_sub(jwt_payload)
    db = _db(request)

    async with db.transaction() as conn:
        rows = await get_transactions_page(conn, UUID(sub_id), cursor, page_size)

    has_more = len(rows) > page_size
    page = rows[:page_size]

    def _cdr_ref(row: dict) -> str | None:
        if row["reference_type"] == "cdr" and row["reference_id"] is not None:
            return str(row["reference_id"])
        return None

    items = [
        TransactionItem(
            id=row["id"],
            transaction_type=row["transaction_type"],
            amount_paise=row["amount_paise"],
            balance_after_paise=row["balance_after_paise"],
            cdr_reference=_cdr_ref(row),
            description=row["description"],
            created_at=row["created_at"],
        )
        for row in page
    ]

    next_cursor = str(page[-1]["id"]) if (has_more and page) else None

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            [item.model_dump(mode="json") for item in items],
            trace_id=_trace_id(request),
            next_cursor=next_cursor,
        ),
    )


@router.get("/plan", status_code=200)
async def get_plan(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return the subscriber's active plan details (AC #1, #2).

    Returns the plan's name, validity expiry (``end_date``), nominal validity
    days, and bundled quotas (allowances). ``days_remaining`` is the countdown to
    ``end_date``. Used-vs-allowance is NOT aggregated here — the frontend composes
    it from GET /usage (Story 3.2).

    Owner assertion: ``subscriber_id`` is the JWT ``sub`` (``_require_sub``).
    """
    sub_id = _require_sub(jwt_payload)
    db = _db(request)

    async with db.transaction() as conn:
        plan = await get_active_plan(conn, UUID(sub_id))

    if plan is None:
        raise NotFoundError("No active plan subscription found.")

    end_date = plan["end_date"]
    days_remaining = (end_date - datetime.now(UTC)).days if end_date is not None else None

    data_limit_mb = plan["data_limit_mb"]
    data_gb = round(data_limit_mb / 1024, 2) if data_limit_mb is not None else None

    resp = ActivePlanResponse(
        plan_id=plan["plan_id"],
        plan_name=plan["plan_name"],
        validity_expiry=end_date,
        validity_days=plan["validity_days"],
        days_remaining=days_remaining,
        quotas=PlanQuotas(
            data_gb=data_gb,
            voice_minutes=plan["voice_minutes"],
            sms_count=plan["sms_count"],
        ),
        roaming_enabled=False,
    )
    return JSONResponse(
        status_code=200,
        content=success_envelope(resp.model_dump(mode="json"), trace_id=_trace_id(request)),
    )
