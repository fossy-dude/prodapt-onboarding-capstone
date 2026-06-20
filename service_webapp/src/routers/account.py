"""Subscriber account router (FR-1-7; architecture §1.12.1 line 1051).

Story 1.6 adds ``POST /api/v1/subscriber/register`` — the multi-step registration
endpoint. It validates the Step 1 (personal details + alternate mobile) and Step 2
(TRAI CAF) payload, persists the registration in a single transaction, provisions
the passwordless Cognito user, and returns the standard success envelope carrying
the generated Registration ID (AC #1, #2, #5, #8).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.errors import DomainError
from core.responses import success_envelope
from services.registration import (
    REGISTRATION_STATUS,
    RegistrationCommand,
    RegistrationService,
    generate_registration_id,
)

router = APIRouter(prefix="/api/v1/subscriber", tags=["subscriber"])

# Indian MSISDN / mobile: 10-15 digits (store the digit string; the DB column is VARCHAR(15)).
_MSISDN_RE = re.compile(r"^\d{10,15}$")
_ID_PROOF_TYPES = Literal["Aadhaar", "PAN", "Passport", "Voter ID"]


class RegisterRequest(BaseModel):
    """Registration payload: Step 1 personal details + Step 2 TRAI CAF fields."""

    model_config = ConfigDict(extra="ignore")

    # Step 1 — personal details (UX brief §5)
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)
    msisdn: str = Field(description="Mobile number being activated (10-15 digits).")
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

    @field_validator("msisdn", "alternate_mobile")
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
        msisdn=payload.msisdn,
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


__all__ = ["RegisterRequest", "router"]
