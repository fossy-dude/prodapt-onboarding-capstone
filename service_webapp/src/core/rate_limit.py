"""Per-subscriber rate-limit middleware (Story 4.3; architecture §1.7.3).

MVP mode: ``RATE_LIMITING_ENABLED=false`` (default). All requests pass through;
``X-RateLimit-Limit`` and ``X-RateLimit-Channel`` headers are set for observability.

Full mode (``RATE_LIMITING_ENABLED=true``): enforces 100 RPM per-subscriber
per-channel using a Valkey sliding-window counter
(key: ``ratelimit:{msisdn}:{channel}:{minute_bucket}``, TTL 60s).

Channels: ``ussd`` (``/api/v1/ussd/*``), ``chatbot`` (``/api/chat/*``), ``api`` (all others).
Paths without a valid JWT (``/health``, ``/ready``, ``/api/v1/ussd/callback``) are
never rate-limited (AC #6).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import jwt as pyjwt
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request
    from starlette.responses import Response

    from core.config import Settings

logger = logging.getLogger(__name__)

_BYPASS_PATHS = frozenset({"/health", "/ready", "/api/v1/ussd/callback"})


def _resolve_channel(path: str) -> str:
    if path.startswith("/api/v1/ussd/"):
        return "ussd"
    if path.startswith("/api/chat/"):
        return "chatbot"
    return "api"


def _extract_msisdn(auth_header: str) -> str | None:
    """Decode JWT payload without signature verification; return ``phone_number`` claim or None.

    Uses PyJWT (already a dep from Story 1.8) with verify_signature=False so the
    middleware does not re-verify the token — the route handler's require_role does that.
    """
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer ") :]
    if not token:
        return None
    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
        return claims.get("phone_number") or claims.get("username")
    except Exception:
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window 100-RPM rate limiter per subscriber per channel.

    Instantiated by ``create_app`` with ``settings`` injected. Cache is resolved
    from ``request.app.state.cache_adapter`` at dispatch time (consistent with the
    rest of the app's adapter-access pattern). The ``_rpm_limit`` class variable is
    populated from ``notification_threshold_config`` during lifespan startup via
    :meth:`load_config`.
    """

    _rpm_limit: int = 100

    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    @classmethod
    async def load_config(cls, db) -> None:
        """Read ``rate_limit_rpm`` from ``notification_threshold_config`` table.

        Falls back to 100 if the table doesn't exist yet (migration not applied)
        or the key is absent — avoids crashing during first-time boot.
        """
        try:
            async with db.transaction() as conn:
                cur = await conn.execute(
                    "SELECT value FROM notification_threshold_config WHERE key = %s",
                    ("rate_limit_rpm",),
                )
                row = await cur.fetchone()
                if row is not None:
                    cls._rpm_limit = int(row[0])
                    logger.info("RateLimitMiddleware: rpm_limit=%d (from DB)", cls._rpm_limit)
                else:
                    logger.info("RateLimitMiddleware: rate_limit_rpm not in DB, using default %d", cls._rpm_limit)
        except Exception as exc:
            logger.warning(
                "RateLimitMiddleware: could not load rpm_limit from DB (using default %d): %s",
                cls._rpm_limit,
                exc,
            )

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Enforce rate limit or pass through; set observability headers."""
        path = request.url.path

        if path in _BYPASS_PATHS:
            return await call_next(request)

        msisdn = _extract_msisdn(request.headers.get("Authorization", ""))
        channel = _resolve_channel(path)

        if msisdn is None:
            return await call_next(request)

        if not self._settings.rate_limiting_enabled:
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self._rpm_limit)
            response.headers["X-RateLimit-Channel"] = channel
            return response

        cache = request.app.state.cache_adapter
        minute_bucket = int(time.time()) // 60
        key = f"ratelimit:{msisdn}:{channel}:{minute_bucket}"
        count = await cache.incr_with_expire(key, 60)

        if count > self._rpm_limit:
            retry_after = 60 - (int(time.time()) % 60)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"100 RPM limit reached. Try again in {retry_after}s",
                    }
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._rpm_limit)
        response.headers["X-RateLimit-Channel"] = channel
        return response
