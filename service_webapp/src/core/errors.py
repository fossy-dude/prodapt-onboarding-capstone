"""Domain errors and the standard error-envelope exception handlers (Story 1.6).

Domain logic raises :class:`DomainError` subclasses carrying a stable ``code`` and
HTTP status; :func:`register_exception_handlers` maps every such error (and FastAPI
validation errors) onto the standard §1.11.3 error envelope::

    {"error": {"code": "...", "message": "...", "detail": {...}}, "meta": {"trace_id": "...", "timestamp": "..."}}

This is the shared error machinery the registration endpoint (and later stories)
reuse — Story 1.4 only had a private ``_error_envelope`` helper in the health router.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class DomainError(Exception):
    """Base domain error — carries a stable ``code`` and intended HTTP status."""

    code: str = "DOMAIN_ERROR"
    http_status: int = 400
    message: str = "Domain error"

    def __init__(self, message: str | None = None, *, detail: dict[str, Any] | None = None) -> None:
        self.message = message if message is not None else self.message
        self.detail: dict[str, Any] = detail or {}
        super().__init__(self.message)


class DuplicateMsisdnError(DomainError):
    """A subscriber with the given MSISDN already exists (AC #8)."""

    code = "DUPLICATE_MSISDN"
    http_status = 409
    message = "A subscriber with this mobile number already exists."


class CognitoProvisioningError(DomainError):
    """The MiniStack Cognito user could not be provisioned (AC #7)."""

    code = "COGNITO_PROVISIONING_FAILED"
    http_status = 502
    message = "Could not provision the identity user."


class UnauthenticatedError(DomainError):
    """Missing, invalid, or expired JWT (AC #4; §1.11.3, NFR-7)."""

    code = "UNAUTHENTICATED"
    http_status = 401
    message = "Authentication required."


class ForbiddenError(DomainError):
    """Valid JWT but role does not grant access to the resource (AC #4; NFR-7)."""

    code = "FORBIDDEN"
    http_status = 403
    message = "Insufficient permissions."


class OtpVerificationError(DomainError):
    """OTP invalid or expired — login challenge or step-up (AC #1, #5; §1.7.3).

    Returns 401 because an invalid OTP is an authentication failure whether it
    occurs during the initial login challenge or a mid-session step-up.
    """

    code = "OTP_INVALID"
    http_status = 401
    message = "OTP verification failed — invalid or expired."


class NotFoundError(DomainError):
    """Requested resource does not exist (404)."""

    code = "NOT_FOUND"
    http_status = 404
    message = "Resource not found."


class ConflictError(DomainError):
    """Request conflicts with current state (409)."""

    code = "CONFLICT"
    http_status = 409
    message = "Conflict."


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "unknown")


def _error_body(request: Request, code: str, message: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "detail": detail},
        "meta": {"trace_id": _trace_id(request), "timestamp": datetime.now(UTC).isoformat()},
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Wire domain-error and validation handlers onto ``app`` (§1.11.3 envelopes)."""

    @app.exception_handler(DomainError)
    async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(request, exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop ``ctx`` (it can embed the original exception object, e.g. a ValueError,
        # which is not JSON-serializable). type/loc/msg/input/url remain for clients.
        safe_errors = [{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "VALIDATION_ERROR", "Request validation failed.", {"errors": safe_errors}),
        )


__all__ = [
    "CognitoProvisioningError",
    "DomainError",
    "DuplicateMsisdnError",
    "ForbiddenError",
    "NotFoundError",
    "OtpVerificationError",
    "UnauthenticatedError",
    "register_exception_handlers",
]
