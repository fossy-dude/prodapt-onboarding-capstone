"""Login OTP primitive (Epic 3 — real passwordless login flow).

Distinct from the mid-session step-up OTP (:mod:`core.step_up`).
Lifecycle:
  1. ``issue(identifier, trace_id)`` — mint a 6-digit code, store under
     ``login_otp:{identifier}`` in Valkey with a configurable TTL, publish a
     ``notification.events`` envelope so the code appears on the Notification
     Portal, and return the code.
  2. ``verify(identifier, entered_code)`` — constant-time compare against the
     stored code; deletes the key on a correct match (single-use).

Best-effort publish: if the Kafka producer is not available the OTP is still
stored in Valkey and login still works (operator can read it via ``rpk``).
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.errors import OtpVerificationError
from core.security import mask_msisdn
from models.envelope import EventEnvelope

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol

logger = logging.getLogger(__name__)

_LOGIN_OTP_PREFIX = "login_otp:"
_OTP_LENGTH = 6
_NOTIFICATION_TOPIC = "notification.events"
_TRACE_RE = re.compile(r"^[0-9a-f]{32}$")
_ZERO_TRACE = "0" * 32


def _safe_trace(trace_id: str) -> str:
    return trace_id if _TRACE_RE.match(trace_id) else _ZERO_TRACE


class LoginOtpService:
    """Generate and validate login OTP codes stored in Valkey; publish to notification.events."""

    def __init__(
        self,
        cache: CacheProtocol,
        ttl_seconds: int = 300,
        producer: Any = None,
    ) -> None:
        self._cache = cache
        self._ttl = ttl_seconds
        self._producer = producer

    def _key(self, identifier: str) -> str:
        return f"{_LOGIN_OTP_PREFIX}{identifier}"

    async def issue(self, identifier: str, trace_id: str) -> str:
        """Mint a 6-digit OTP, store it in Valkey, publish to notification.events, return it."""
        code = "".join(secrets.choice("0123456789") for _ in range(_OTP_LENGTH))
        await self._cache.set_str(self._key(identifier), code, ex=self._ttl)
        logger.info("Login OTP issued for identifier=***%s (ttl=%ds)", identifier[-4:], self._ttl)
        await self._publish(identifier, code, trace_id)
        return code

    async def verify(self, identifier: str, entered_code: str) -> bool:
        """Validate ``entered_code``; delete key on success (single-use).

        Returns False on wrong or absent code — never raises.
        """
        stored = await self._cache.get_str(self._key(identifier))
        if stored is None or not hmac.compare_digest(stored, entered_code):
            logger.info("Login OTP verification failed for identifier=***%s", identifier[-4:])
            return False
        try:
            await self._cache.delete(self._key(identifier))
        except Exception:
            logger.warning("Login OTP: cache delete failed for identifier=***%s — key may replay", identifier[-4:])
        logger.info("Login OTP verified and consumed for identifier=***%s", identifier[-4:])
        return True

    async def _publish(self, identifier: str, code: str, trace_id: str) -> None:
        if self._producer is None:
            logger.warning(
                "kafka_producer not initialised — login OTP not published (identifier=***%s)", identifier[-4:]
            )
            return
        payload: dict[str, Any] = {
            "msisdn": identifier,
            "msisdn_last4": mask_msisdn(identifier),
            "notification_type": "LOGIN_OTP",
            "channel": "SMS",
            "message_preview": f"Your SBOAI login code is {code}. Valid for 5 minutes.",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        envelope = EventEnvelope.new(
            event_type=_NOTIFICATION_TOPIC,
            payload=payload,
            trace_id=_safe_trace(trace_id),
        )
        traceparent = f"00-{_safe_trace(trace_id)}-{'0' * 16}-01"
        headers = [("traceparent", traceparent.encode())]
        try:
            await self._producer.send(
                _NOTIFICATION_TOPIC,
                value=envelope.model_dump_json().encode(),
                key=identifier.encode(),
                headers=headers,
            )
        except Exception:
            logger.warning("Login OTP publish failed for identifier=***%s — OTP still valid in Valkey", identifier[-4:])


class FakeLoginOtpService:
    """In-memory login OTP service for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.issued: list[str] = []
        self.published_login_otps: list[dict[str, Any]] = []

    async def issue(self, identifier: str, trace_id: str) -> str:
        """Generate and store an OTP for ``identifier`` (in-memory)."""
        code = "".join(secrets.choice("0123456789") for _ in range(_OTP_LENGTH))
        self._store[identifier] = code
        self.issued.append(code)
        self.published_login_otps.append({"identifier": identifier, "code": code, "trace_id": trace_id})
        return code

    async def verify(self, identifier: str, entered_code: str) -> bool:
        """Validate ``entered_code`` and delete the key on success."""
        stored = self._store.get(identifier)
        if stored is None or not hmac.compare_digest(stored, entered_code):
            return False
        del self._store[identifier]
        return True


__all__ = [
    "FakeLoginOtpService",
    "LoginOtpService",
]
