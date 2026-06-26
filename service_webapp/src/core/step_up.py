"""Mid-session step-up OTP primitive (Story 1.8; §1.7.3, AC #5).

Distinct from the Cognito login OTP (which is handled entirely by Cognito's Custom
Auth Flow). Step-up is a second-factor guard for sensitive mid-session actions
(SIM-binding change, high-value recharge) where Cognito cannot cleanly interrupt an
already-authenticated session.

Key lifecycle (§1.7.3):
  1. ``generate(msisdn)`` → 6-digit code stored as ``otp:{msisdn}`` STRING in Valkey
     with a 5-minute (300 s) TTL (configurable via ``settings.otp_step_up_ttl_seconds``).
  2. ``verify(msisdn, entered_code)`` → validates the stored code; deletes the key on
     success (single-use); returns ``False`` on wrong/absent code.

Callers that want a FastAPI dependency use :func:`require_step_up`, which wires the
service from ``request.app.state.step_up_service`` and raises
:class:`~core.errors.OtpVerificationError` on failure.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Request

from core.errors import OtpVerificationError

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol

logger = logging.getLogger(__name__)

_OTP_PREFIX = "otp:"
_OTP_LENGTH = 6


class StepUpOtpService:
    """Generate and validate mid-session step-up OTP codes stored in Valkey."""

    def __init__(self, cache: CacheProtocol, ttl_seconds: int = 300) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    def _key(self, msisdn: str) -> str:
        return f"{_OTP_PREFIX}{msisdn}"

    async def generate(self, msisdn: str) -> str:
        """Generate a random 6-digit code, store it in Valkey, return the code.

        PII note: ``msisdn`` is part of the Valkey key (server-side only) — never
        log it raw; log only ``msisdn[-4:]`` per §1.11.6.
        """
        code = "".join(secrets.choice("0123456789") for _ in range(_OTP_LENGTH))
        await self._cache.set_str(self._key(msisdn), code, ex=self._ttl)
        logger.info("Step-up OTP generated for msisdn=***%s (ttl=%ds)", msisdn[-4:], self._ttl)
        return code

    async def verify(self, msisdn: str, entered_code: str) -> bool:
        """Validate ``entered_code`` against the stored OTP.

        Deletes the Valkey key on a correct match (single-use). Returns ``False``
        when the key is absent (expired or never generated) or the code is wrong.
        """
        stored = await self._cache.get_str(self._key(msisdn))
        # P2: constant-time comparison prevents timing-based OTP enumeration.
        if stored is None or not hmac.compare_digest(stored, entered_code):
            logger.info("Step-up OTP verification failed for msisdn=***%s", msisdn[-4:])
            return False
        try:
            # P16: delete key first to prevent replay on cache errors.
            await self._cache.delete(self._key(msisdn))
        except Exception:
            logger.warning("Step-up OTP: cache delete failed for msisdn=***%s — key may replay", msisdn[-4:])
        logger.info("Step-up OTP verified and consumed for msisdn=***%s", msisdn[-4:])
        return True


class FakeStepUpOtpService:
    """In-memory step-up OTP service for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.generated: list[str] = []

    async def generate(self, msisdn: str) -> str:
        """Generate and store an OTP for ``msisdn`` (in-memory)."""
        code = "".join(secrets.choice("0123456789") for _ in range(_OTP_LENGTH))
        self._store[msisdn] = code
        self.generated.append(code)
        return code

    async def verify(self, msisdn: str, entered_code: str) -> bool:
        """Validate ``entered_code`` and delete the key on success."""
        stored = self._store.get(msisdn)
        # P2: constant-time comparison mirrors the real service.
        if stored is None or not hmac.compare_digest(stored, entered_code):
            return False
        del self._store[msisdn]
        return True


def require_step_up(msisdn_attr: str = "msisdn") -> Any:
    """Return a FastAPI ``Depends`` that validates the step-up OTP for a request.

    The caller must have already set ``request.state.{msisdn_attr}`` (typically done
    by :func:`~core.auth.require_role`). The OTP code is expected in the request body
    field ``step_up_otp``.

    Raises :class:`~core.errors.OtpVerificationError` on wrong/expired code.
    """

    async def _guard(request: Request) -> None:
        service = getattr(request.app.state, "step_up_service", None)
        if service is None:
            raise RuntimeError("step_up_service not wired onto app.state")
        # P15: empty msisdn produces key "otp:" which could collide across users.
        msisdn: str = getattr(request.state, msisdn_attr, "")
        if not msisdn:
            raise OtpVerificationError("MSISDN context missing — cannot validate step-up OTP.")
        # P3: request.json() may raise if body already consumed or Content-Type wrong.
        try:
            body: dict[str, Any] = await request.json()
        except Exception as exc:
            raise OtpVerificationError("Invalid request body for step-up OTP.") from exc
        entered_code: str = body.get("step_up_otp", "")
        if not await service.verify(msisdn, entered_code):
            raise OtpVerificationError()

    return Depends(_guard)


__all__ = [
    "FakeStepUpOtpService",
    "StepUpOtpService",
    "require_step_up",
]
