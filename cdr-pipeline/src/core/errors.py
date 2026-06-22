"""Domain errors and standard error-envelope exception handlers (ported from service_webapp, Story 2.5).

Minimal port — only the error types and handlers needed by the cdr-pipeline
management API. The envelope contract is identical to §1.11.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class DomainError(Exception):
    """Base domain error carrying a stable ``code`` and HTTP status."""

    code: str = "DOMAIN_ERROR"
    http_status: int = 400
    message: str = "Domain error"

    def __init__(self, message: str | None = None, *, detail: dict[str, Any] | None = None) -> None:
        self.message = message if message is not None else self.message
        self.detail: dict[str, Any] = detail or {}
        super().__init__(self.message)


class UnauthenticatedError(DomainError):
    """Missing, invalid, or expired JWT."""

    code = "UNAUTHENTICATED"
    http_status = 401
    message = "Authentication required."


class ForbiddenError(DomainError):
    """Valid JWT but role does not grant access."""

    code = "FORBIDDEN"
    http_status = 403
    message = "Insufficient permissions."


class NotFoundError(DomainError):
    """Requested resource does not exist."""

    code = "NOT_FOUND"
    http_status = 404
    message = "Resource not found."


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
        safe_errors = [{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "VALIDATION_ERROR", "Request validation failed.", {"errors": safe_errors}),
        )


__all__ = [
    "DomainError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthenticatedError",
    "register_exception_handlers",
]
