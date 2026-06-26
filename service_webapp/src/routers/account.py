"""Subscriber account router (FR-1-7; architecture §1.12.1 line 1051).

Story 1.6 adds ``POST /api/v1/subscriber/register``.
Story 1.7 adds the SIM activation order status endpoints:
  - ``GET /api/v1/subscriber/orders/{order_id}/status`` — poll order state
  - ``GET /api/v1/subscriber/orders/active`` — discover the subscriber's active order
Story 1.8 adds the passwordless login flow under ``/api/v1/auth``:
  - ``POST /api/v1/auth/login/initiate`` — start Cognito Custom Auth Flow
  - ``POST /api/v1/auth/login/verify`` — verify OTP, return JWT tokens
Story 1.9 adds the profile management endpoints:
  - ``GET /api/v1/subscriber/profile`` — read the decrypted profile + KYC status
  - ``PATCH /api/v1/subscriber/profile`` — edit email/address (audit + re-write)
Story 1.10 adds the payment methods endpoints:
  - ``POST /api/v1/account/payment-methods`` — add a saved payment method
  - ``GET /api/v1/account/payment-methods`` — list saved payment methods
  - ``PATCH /api/v1/account/payment-methods/{id}/default`` — set default payment method
  - ``DELETE /api/v1/account/payment-methods/{id}` — delete a payment method
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from psycopg.types.json import Json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.auth import require_role
from core.errors import DomainError, ForbiddenError, NotFoundError
from core.responses import success_envelope
from core.security import mask_msisdn, normalize_login_identifier
from routers._identity import resolve_subscriber_id
from services.registration import (
    REGISTRATION_STATUS,
    RegistrationCommand,
    RegistrationService,
    generate_registration_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subscriber", tags=["subscriber"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
account_router = APIRouter(prefix="/api/v1/account", tags=["account"])

# Indian MSISDN / mobile: 10-15 digits (store the digit string; the DB column is VARCHAR(15)).
_MSISDN_RE = re.compile(r"^\d{10,15}$")
_ID_PROOF_TYPES = Literal["Aadhaar", "PAN", "Passport", "Voter ID"]


class RegisterRequest(BaseModel):
    """Registration payload: Step 1 personal details + Step 2 TRAI CAF fields.

    MSISDN is intentionally absent — it is auto-generated at SIM activation time.
    """

    model_config = ConfigDict(extra="ignore")

    # Step 1 — personal details (UX brief §5)
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)
    alternate_mobile: str = Field(description="Alternate mobile for the pre-activation OTP (PRD A-6).")

    # Step 2 — TRAI CAF fields (UX brief §5)
    date_of_birth: str = Field(description="ISO date (YYYY-MM-DD).")
    address_line1: str = Field(min_length=1)
    address_line2: str = ""
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    pin_code: str = Field(min_length=1)
    id_proof_type: _ID_PROOF_TYPES
    id_proof_number: str = Field(min_length=1)
    consent: bool = Field(description="Data-processing consent (must be True).")

    @field_validator("alternate_mobile")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        if not _MSISDN_RE.match(v):
            raise ValueError("must be 10-15 digits")
        return v

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("must be a valid email address")
        return v

    @field_validator("consent")
    @classmethod
    def _consent_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("consent is required to submit the TRAI CAF")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _validate_dob(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("date_of_birth must be a valid calendar date (YYYY-MM-DD)") from exc
        return v


def _service(request: Request) -> RegistrationService:
    """Resolve the registration service wired onto app.state.

    If the service was never wired (e.g. the ASGI lifespan did not run), surface a
    503 rather than a confusing 500.
    """
    service = getattr(request.app.state, "registration_service", None)
    if service is None:
        err = DomainError("Registration service is not initialised — lifespan may not have run.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return service


def _to_command(payload: RegisterRequest) -> RegistrationCommand:
    return RegistrationCommand(
        full_name=payload.full_name,
        email=payload.email,
        alternate_mobile=payload.alternate_mobile,
        date_of_birth=payload.date_of_birth,
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        pin_code=payload.pin_code,
        id_proof_type=payload.id_proof_type,
        id_proof_number=payload.id_proof_number,
        consent=payload.consent,
        registration_id=generate_registration_id(datetime.now(UTC)),
    )


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request) -> JSONResponse:
    """Register a new subscriber and return the generated Registration ID (AC #1, #2, #5)."""
    service = _service(request)
    result = await service.register(_to_command(payload))
    return JSONResponse(
        status_code=201,
        content=success_envelope(
            {"registration_id": result.registration_id, "status": REGISTRATION_STATUS},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


class LoginInitiateRequest(BaseModel):
    """Initiate passwordless login: Registration ID (pre-activation) or MSISDN (post-activation)."""

    model_config = ConfigDict(extra="ignore")

    # P9: bound length to prevent unbounded strings reaching Cognito.
    identifier: str = Field(min_length=1, max_length=128, description="Registration ID or MSISDN.")

    @field_validator("identifier")
    @classmethod
    def _normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)


class LoginVerifyRequest(BaseModel):
    """Verify the OTP challenge and receive JWT tokens."""

    model_config = ConfigDict(extra="ignore")

    # P9: min/max length guards prevent malformed inputs reaching Cognito.
    identifier: str = Field(
        min_length=1, max_length=128, description="Registration ID or MSISDN (must match initiation)."
    )
    otp: str = Field(min_length=6, max_length=6, description="6-digit OTP delivered via the Notification Portal.")

    @field_validator("identifier")
    @classmethod
    def _normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)


def _cognito(request: Request):
    """Resolve the Cognito provider from app state (injected by lifespan or tests)."""
    provider = getattr(request.app.state, "cognito_provider", None)
    if provider is None:
        err = DomainError("Cognito provider is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return provider


def _login_otp_service(request: Request):
    """Resolve the login OTP service from app state (injected by lifespan or tests)."""
    svc = getattr(request.app.state, "login_otp_service", None)
    if svc is None:
        err = DomainError("Login OTP service is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return svc


@auth_router.post("/login/initiate", status_code=200)
async def login_initiate(payload: LoginInitiateRequest, request: Request) -> JSONResponse:
    """Initiate passwordless login — mint an OTP, store in Valkey, publish to notification.events.

    The OTP appears on the Notification Portal (/simulator/notifications). No session
    string is returned; the client sends only identifier + otp to /login/verify.
    """
    provider = _cognito(request)
    otp_svc = _login_otp_service(request)
    trace_id = getattr(request.state, "trace_id", "unknown")
    await provider.initiate_login(payload.identifier, trace_id, otp_svc)
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {},
            trace_id=trace_id,
        ),
    )


@auth_router.post("/login/verify", status_code=200)
async def login_verify(payload: LoginVerifyRequest, request: Request) -> JSONResponse:
    """Verify the OTP and return JWT access + refresh tokens (AC #1, #2).

    On success the access token (30 min TTL) and refresh token (30 days) are returned.
    The caller stores the access token and sends it as ``Authorization: Bearer {token}``
    on subsequent requests.
    """
    provider = _cognito(request)
    otp_svc = _login_otp_service(request)
    tokens = await provider.verify_login_otp(payload.identifier, payload.otp, otp_svc)
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            tokens,
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


class TokenRefreshRequest(BaseModel):
    """Exchange a Cognito refresh token for a new access token."""

    model_config = ConfigDict(extra="ignore")

    refresh_token: str = Field(min_length=1, max_length=2048)


@auth_router.post("/token/refresh", status_code=200)
async def token_refresh(payload: TokenRefreshRequest, request: Request) -> JSONResponse:
    """Exchange a refresh token for a new access token.

    Returns ``{access_token, id_token, token_type}``.
    Responds 401 UNAUTHENTICATED when the refresh token is invalid or expired.
    """
    from core.errors import OtpVerificationError  # noqa: PLC0415

    provider = _cognito(request)
    try:
        tokens = await provider.refresh_token(payload.refresh_token)
    except OtpVerificationError as exc:
        err = DomainError(str(exc))
        err.code = "UNAUTHENTICATED"
        err.http_status = 401
        raise err from exc
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            tokens,
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


def _db(request: Request):
    """Resolve the database adapter from app state."""
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised — lifespan may not have run.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _validate_order_id(order_id: str) -> None:
    """Reject non-UUID ``order_id`` path params as 404 before they reach SQL.

    A malformed value would otherwise hit the ``%s::uuid`` cast and raise a
    psycopg ``DataError`` → unhandled 500. Treating it as 404 keeps the
    behaviour uniform with the unknown-order path (no existence oracle).
    """
    try:
        uuid.UUID(order_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError("Order not found.") from exc


# ── SIM Activation Order Status (Story 1.7) ──────────────────────────────────


@router.get("/orders/active", status_code=200)
async def get_active_order(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return the subscriber's active NEW_ACTIVATION order (AC #1; discovery for the tracker UI).

    Returns the most recent ``NEW_ACTIVATION`` order row so the tracker frontend
    can obtain the ``order_id`` without it being embedded in the JWT or URL.
    When the subscriber has no active order, returns HTTP 200 with
    ``order_id: null`` so the tracker can render an empty state rather than an
    error (a missing order is a legitimate state, not a failure).
    """
    db = _db(request)
    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(
            """
            SELECT id::text, fulfilment_status, modified_at
            FROM ops_order_fulfilment
            WHERE subscriber_id = %s::uuid
              AND fulfilment_type = 'NEW_ACTIVATION'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sub,),
        )
        row = await cur.fetchone()
    if row is None:
        return JSONResponse(
            status_code=200,
            content=success_envelope(
                {"order_id": None, "status": None, "updated_at": None},
                trace_id=getattr(request.state, "trace_id", "unknown"),
            ),
        )
    order_id, status, updated_at = row
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"order_id": order_id, "status": status, "updated_at": updated_at.isoformat()},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


@router.get("/orders/{order_id}/status", status_code=200)
async def get_order_status(
    order_id: str,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return the current fulfilment status for ``order_id`` (AC #2, #5).

    Authorises that the JWT ``sub`` (subscriber UUID) matches the order's
    ``subscriber_id``; mismatches yield HTTP 403 (own-order authorisation).
    MSISDN is included in the response **only** when ``status = 'ACTIVATED'``
    (PII hygiene: never log raw MSISDN; use ``msisdn[-4:]`` if needed).
    """
    _validate_order_id(order_id)
    db = _db(request)
    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(
            """
            SELECT o.fulfilment_status,
                   o.modified_at,
                   o.subscriber_id::text,
                   s.msisdn
            FROM ops_order_fulfilment o
            JOIN identity_subscribers s ON s.id = o.subscriber_id
            WHERE o.id = %s::uuid
            """,
            (order_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFoundError("Order not found.")
    status, updated_at, subscriber_id, msisdn = row
    if str(subscriber_id) != sub:
        logger.info("order-status 403: sub=%s order_id=%s", sub, order_id)
        raise ForbiddenError("You are not authorised to view this order.")
    msisdn_out = msisdn if status == "ACTIVATED" else None
    if msisdn_out is not None:
        logger.debug("order-status ACTIVATED sub=%s msisdn=%s", sub, mask_msisdn(msisdn_out))
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {
                "status": status,
                "updated_at": updated_at.isoformat(),
                "msisdn": msisdn_out,
            },
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


# ── Profile Management (Story 1.9) ───────────────────────────────────────────
#
# PII model (user decision 2026-06-20; security.py + V3 migration comment):
# name/email/address are stored PLAINTEXT in identity_subscribers — encryption is
# an application-layer concern for consumption/sharing, NOT a DB-column concern.
# So "decrypt-on-read" here is reading the stored value for the authenticated
# OWNER only; pgcrypto is not involved. PII never reaches logs/spans (NFR-16) —
# only the subscriber UUID (and msisdn[-4:] where relevant) is logged.

_EDITABLE_ADDRESS_FIELDS = ("address_line1", "address_line2", "city", "state", "pin_code")

# Single source of truth for the profile SELECT (used by both GET and PATCH re-read).
# The LATERAL join picks the subscriber's MOST RECENT KYC record (status only — the
# KYC status itself is seeded/simulated elsewhere; this story only reads it).
_PROFILE_SELECT = """
    SELECT s.subscriber_name,
           s.email,
           s.address_line1,
           s.address_line2,
           s.city,
           s.state,
           s.pin_code,
           k.kyc_status
    FROM identity_subscribers s
    LEFT JOIN LATERAL (
        SELECT kyc_status
        FROM identity_kyc_records
        WHERE subscriber_id = s.id
        ORDER BY created_at DESC
        LIMIT 1
    ) k ON TRUE
    WHERE s.id = %s::uuid
"""


def _profile_data(row: tuple) -> dict:
    """Shape a profile SELECT row into the response ``data`` object.

    ``kyc_status`` is normalised to lowercase (Badge variants are
    verified/pending/rejected); a NULL/empty status defaults to ``"pending"``.
    """
    name, email, addr1, addr2, city, state, pin, kyc_status = row
    kyc = (kyc_status or "").strip().lower() or "pending"
    return {
        "name": name,
        "email": email,
        "address": {
            "line1": addr1,
            "line2": addr2,
            "city": city,
            "state": state,
            "pin_code": pin,
        },
        "kyc_status": kyc,
    }


@router.get("/profile", status_code=200)
async def get_profile(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return the caller's decrypted profile + KYC status (AC #1, #2, #6, #7).

    The target subscriber is resolved from the JWT ``sub`` claim — never from a
    client-supplied id — so owner-only access is enforced by construction. The KYC
    status comes from the subscriber's latest ``identity_kyc_records`` row.
    """
    db = _db(request)
    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(_PROFILE_SELECT, (sub,))
        row = await cur.fetchone()
    if row is None:
        raise NotFoundError("Subscriber profile not found.")
    return JSONResponse(
        status_code=200,
        content=success_envelope(_profile_data(row), trace_id=getattr(request.state, "trace_id", "unknown")),
    )


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields (AC #3). Name is read-only; email + address editable."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=254)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    pin_code: str | None = Field(default=None, max_length=10)

    @field_validator("email", "address_line1", "address_line2", "city", "state", "pin_code", mode="before")
    @classmethod
    def _strip_empty(cls, v: object) -> object:
        """Convert empty/whitespace-only strings to None so they are treated as no-op updates."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("must be a valid email address")
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self) -> ProfileUpdateRequest:
        if all(getattr(self, f) is None for f in ("email", *_EDITABLE_ADDRESS_FIELDS)):
            raise ValueError("Provide at least one field to update.")
        return self


@router.patch("/profile", status_code=200)
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Edit the caller's email/address: re-write + append an audit row (AC #3, #4, #6).

    PII is stored plaintext (user decision 2026-06-20); the UPDATE simply writes the
    new values and the V2 trigger advances ``modified_at``. A single append-only
    ``billing_audit_log`` row (``action='UPDATE_PROFILE'``) records the edit — its
    ``new_value`` carries the changed FIELD NAMES only, never raw PII (§1.11.6).
    Returns HTTP 200 with the updated decrypted profile in the standard envelope.
    """
    db = _db(request)
    updates = {
        field: getattr(payload, field)
        for field in ("email", *_EDITABLE_ADDRESS_FIELDS)
        if getattr(payload, field) is not None
    }
    # Column names come from a fixed allow-list (the model fields), so building the
    # SET clause by string is safe — values are still bound via %s parameters.
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(
            f"UPDATE identity_subscribers SET {set_clause} WHERE id = %s::uuid",
            (*updates.values(), sub),
        )
        if cur.rowcount == 0:
            # No matching subscriber — rolls back (no audit row written).
            raise NotFoundError("Subscriber profile not found.")
        await conn.execute(
            """
            INSERT INTO billing_audit_log (entity_type, entity_id, action, actor_id, actor_type, new_value)
            VALUES (%s, %s::uuid, %s, %s, %s, %s)
            """,
            (
                "SUBSCRIBER_PROFILE",
                sub,
                "UPDATE_PROFILE",
                sub,
                "SUBSCRIBER",
                Json({"fields_updated": sorted(updates.keys())}),
            ),
        )
        cur = await conn.execute(_PROFILE_SELECT, (sub,))
        row = await cur.fetchone()
    if row is None:  # defensive: rowcount > 0 guarantees the SELECT finds it
        raise NotFoundError("Subscriber profile not found.")
    logger.info("profile updated: sub=%s fields=%s", sub, sorted(updates.keys()))
    return JSONResponse(
        status_code=200,
        content=success_envelope(_profile_data(row), trace_id=getattr(request.state, "trace_id", "unknown")),
    )


# ── Payment Methods (Story 1.10) ─────────────────────────────────────────────

_PAYMENT_METHOD_TYPES = Literal["CREDIT_CARD", "UPI", "NET_BANKING", "MOBILE_WALLET"]


def _looks_like_raw_pan(token: str) -> bool:
    """Check whether the token looks like a raw PAN.

    Returns ``True`` if the token is 13-19 contiguous digits OR passes the Luhn
    algorithm. Client-side tokenisation is the design, but if a bug sends a raw
    PAN to the server, we must reject it (HTTP 422) and NEVER persist or log it.
    """
    # Check for 13-19 contiguous digits (raw PAN length range)
    if re.match(r"^\d{13,19}$", token):
        return True
    # Luhn algorithm check (catches formatted PANs like "4242-4242-4242-4242")
    digits = re.sub(r"\D", "", token)
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class AddPaymentMethodRequest(BaseModel):
    """Payload to add a saved payment method (AC #1, #3, #4)."""

    model_config = ConfigDict(extra="forbid")

    type: _PAYMENT_METHOD_TYPES
    token: str = Field(min_length=1, max_length=256, description="Tokenised card (UUID) or identifier (UPI/wallet).")
    display_label: str = Field(min_length=1, max_length=100, description="Human-readable label (e.g., '•••• 4242').")

    @field_validator("token")
    @classmethod
    def _reject_raw_pan(cls, v: str) -> str:
        if _looks_like_raw_pan(v):
            raise ValueError("token must not be a raw card number (client-side tokenisation is required)")
        return v


@account_router.post("/payment-methods", status_code=201)
async def add_payment_method(
    payload: AddPaymentMethodRequest,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Add a saved payment method for the authenticated subscriber (AC #1, #3).

    The request must contain only ``{type, token, display_label}``. For credit cards,
    the token is a UUID generated client-side; the raw PAN never reaches the server.
    Non-card methods (UPI, net banking, mobile wallet) store the identifier as-is.
    """
    db = _db(request)

    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(
            """
            INSERT INTO recharge_payment_methods (subscriber_id, method_type, token, display_label, is_default)
            VALUES (%s::uuid, %s, %s, %s, false)
            RETURNING id::text, method_type AS type, token, display_label, is_default, created_at
            """,
            (sub, payload.type, payload.token, payload.display_label),
        )
        row = await cur.fetchone()
        if row is None:
            raise DomainError("Failed to create payment method.")
        method_id, type_, token, display_label, is_default, created_at = row

    logger.info("payment-method added: sub=%s id=%s type=%s", sub, method_id, type_)
    return JSONResponse(
        status_code=201,
        content=success_envelope(
            {
                "id": method_id,
                "subscriber_id": sub,
                "type": type_,
                "token": token,
                "display_label": display_label,
                "is_default": is_default,
                "created_at": created_at.isoformat() if created_at else None,
            },
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


@account_router.get("/payment-methods", status_code=200)
async def list_payment_methods(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """List all saved payment methods for the authenticated subscriber (AC #5).

    Returns an array of payment methods with most recent first. Each method includes
    a type icon in the UI and a ``Set Default`` action (unless already default).
    """
    db = _db(request)

    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        cur = await conn.execute(
            """
            SELECT id::text, method_type AS type, token, display_label, is_default, created_at
            FROM recharge_payment_methods
            WHERE subscriber_id = %s::uuid
            ORDER BY created_at DESC
            """,
            (sub,),
        )
        rows = await cur.fetchall()

    methods = [
        {
            "id": row[0],
            "subscriber_id": sub,
            "type": row[1],
            "token": row[2],
            "display_label": row[3],
            "is_default": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
        }
        for row in rows
    ]

    logger.debug("payment-methods listed: sub=%s count=%d", sub, len(methods))
    return JSONResponse(
        status_code=200,
        content=success_envelope(methods, trace_id=getattr(request.state, "trace_id", "unknown")),
    )


@account_router.patch("/payment-methods/{method_id}/default", status_code=200)
async def set_default_payment_method(
    method_id: str,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Set a payment method as the default (AC #5).

    Clears the ``is_default`` flag on all other methods for this subscriber in a
    single transaction (ensuring exactly one default at a time).
    """
    db = _db(request)

    try:
        uuid.UUID(method_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError("Payment method not found.") from exc

    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        # First verify ownership
        cur = await conn.execute(
            """
            SELECT subscriber_id::text FROM recharge_payment_methods
            WHERE id = %s::uuid
            """,
            (method_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Payment method not found.")
        owner_id = row[0]
        if str(owner_id) != sub:
            logger.info("set-default 403: sub=%s method_id=%s owner=%s", sub, method_id, owner_id)
            raise ForbiddenError("You are not authorised to modify this payment method.")

        # Clear default on all methods for this subscriber, then set the new default
        await conn.execute(
            """
            UPDATE recharge_payment_methods
            SET is_default = false
            WHERE subscriber_id = %s::uuid
            """,
            (sub,),
        )
        await conn.execute(
            """
            UPDATE recharge_payment_methods
            SET is_default = true
            WHERE id = %s::uuid AND subscriber_id = %s::uuid
            """,
            (method_id, sub),
        )

        # Re-read to return the updated record
        cur = await conn.execute(
            """
            SELECT id::text, method_type AS type, token, display_label, is_default, created_at
            FROM recharge_payment_methods
            WHERE id = %s::uuid
            """,
            (method_id,),
        )
        row = await cur.fetchone()
        if row is None:  # Should never happen after the UPDATE
            raise NotFoundError("Payment method not found.")

    method_id_out, type_, token, display_label, is_default, created_at = row
    logger.info("payment-method set-default: sub=%s id=%s", sub, method_id)
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {
                "id": method_id_out,
                "subscriber_id": sub,
                "type": type_,
                "token": token,
                "display_label": display_label,
                "is_default": is_default,
                "created_at": created_at.isoformat() if created_at else None,
            },
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


@account_router.delete("/payment-methods/{method_id}", status_code=204)
async def delete_payment_method(
    method_id: str,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> Response:
    """Delete a saved payment method.

    Authorises that the JWT ``sub`` matches the method's ``subscriber_id``; mismatches
    yield HTTP 403. Returns HTTP 204 on success (no body).
    """
    db = _db(request)

    try:
        uuid.UUID(method_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError("Payment method not found.") from exc

    async with db.transaction() as conn:
        sub = await resolve_subscriber_id(conn, jwt_payload)
        # Verify ownership before delete
        cur = await conn.execute(
            """
            SELECT subscriber_id::text FROM recharge_payment_methods
            WHERE id = %s::uuid
            """,
            (method_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Payment method not found.")
        owner_id = row[0]
        if str(owner_id) != sub:
            logger.info("delete 403: sub=%s method_id=%s owner=%s", sub, method_id, owner_id)
            raise ForbiddenError("You are not authorised to delete this payment method.")

        await conn.execute(
            """
            DELETE FROM recharge_payment_methods
            WHERE id = %s::uuid AND subscriber_id = %s::uuid
            """,
            (method_id, sub),
        )

    logger.info("payment-method deleted: sub=%s id=%s", sub, method_id)
    return Response(status_code=204)


__all__ = [
    "AddPaymentMethodRequest",
    "LoginInitiateRequest",
    "LoginVerifyRequest",
    "ProfileUpdateRequest",
    "RegisterRequest",
    "account_router",
    "auth_router",
    "router",
]
