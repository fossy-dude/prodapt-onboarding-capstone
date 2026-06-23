"""Balance and usage endpoints for authenticated subscribers (Story 3.2).

GET /api/v1/subscriber/balance  — current wallet balance (Valkey-authoritative).
GET /api/v1/subscriber/usage    — per-type CDR usage vs plan allowances.

Both endpoints enforce subscriber ownership via ``_require_sub`` (deferred-work D3;
``require_role`` validates groups but does not assert JWT ``sub``).
MSISDN is always masked to last-4 in responses and logs (PII hygiene §1.11.6).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError, NotFoundError, UnauthenticatedError
from core.responses import success_envelope
from core.security import mask_msisdn
from db.billing.queries import (
    get_active_subscription,
    get_usage_for_period,
    get_wallet_balance_from_db,
)
from models.balance import UsageAllowance, UsagePeriod, UsageResponse, WalletBalanceResponse

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
