"""JWT validation + role-based access guard for cdr-pipeline management API (Story 2.5).

Ported from service_webapp/src/core/auth.py — identical contract: RS256 via
Cognito JWKS, ``cognito:groups`` claim, same error types. Duplication is
intentional (MVP two-codebase rule; architecture §1.5.1). Flag as candidate for
a future shared module.

Usage in a management route::

    from core.auth import require_role


    @router.post("/workers/pause")
    async def pause(payload: dict = require_role("admin")): ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Request

from core.errors import ForbiddenError, UnauthenticatedError

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "


def _cognito_jwks_url(settings: Settings) -> str:
    """Build the Cognito JWKS URL for the user pool."""
    return (
        f"{settings.cognito_endpoint_url}"
        f"/{settings.cognito_region}"
        f"/{settings.cognito_user_pool_id}"
        f"/.well-known/jwks.json"
    )


class JWTValidator:
    """Validate Cognito RS256 access tokens via the user pool's JWKS endpoint."""

    def __init__(self, jwks_url: str) -> None:
        self._jwks_url = jwks_url
        self._jwks_client: Any = None

    def _client(self) -> Any:
        if self._jwks_client is None:
            import jwt  # noqa: PLC0415

            self._jwks_client = jwt.PyJWKClient(self._jwks_url, cache_keys=True)
        return self._jwks_client

    def decode(self, token: str) -> dict[str, Any]:
        """Decode ``token``, verify RS256 signature + expiry, return payload dict."""
        import jwt  # noqa: PLC0415

        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            logger.info("JWT validation: token expired")
            raise UnauthenticatedError("Access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            logger.info("JWT validation: invalid token (%s)", type(exc).__name__)
            raise UnauthenticatedError("Access token is invalid.") from exc
        except Exception as exc:
            logger.warning("JWT validation: JWKS/network error (%s)", type(exc).__name__)
            raise UnauthenticatedError("Token validation temporarily unavailable.") from exc


class FakeJWTValidator:
    """Deterministic in-memory JWT validator for unit tests."""

    def __init__(self, payload: dict[str, Any] | None = None, *, fail: str | None = None) -> None:
        self._payload: dict[str, Any] = payload or {}
        self.fail = fail

    def decode(self, token: str) -> dict[str, Any]:
        """Return the fixed payload or raise a simulated auth error."""
        if self.fail == "expired":
            raise UnauthenticatedError("Access token has expired.")
        if self.fail == "invalid":
            raise UnauthenticatedError("Access token is invalid.")
        return self._payload


def _extract_token(request: Request) -> str:
    """Extract the Bearer token string from the ``Authorization`` header."""
    header = request.headers.get("Authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        raise UnauthenticatedError("Missing or malformed Authorization header.")
    token = header[len(_BEARER_PREFIX) :]
    if not token:
        raise UnauthenticatedError("Missing or malformed Authorization header.")
    return token


def require_role(*roles: str) -> Any:
    """Return a FastAPI ``Depends`` that validates the Bearer JWT and checks ``cognito:groups``.

    Raises :class:`~core.errors.UnauthenticatedError` (401) for missing/invalid tokens,
    :class:`~core.errors.ForbiddenError` (403) for valid tokens without required group.
    """

    async def _guard(request: Request) -> dict[str, Any]:
        validator = getattr(request.app.state, "jwt_validator", None)
        if validator is None:
            raise RuntimeError("jwt_validator not wired onto app.state — check lifespan")

        token = _extract_token(request)
        payload = validator.decode(token)

        if roles:
            groups: list[str] = payload.get("cognito:groups") or []
            if not any(r in groups for r in roles):
                logger.info(
                    "JWT role check failed: required=%s got=%s sub=%s",
                    roles,
                    groups,
                    payload.get("sub", "unknown"),
                )
                raise ForbiddenError("Insufficient permissions for this resource.")

        return payload

    return Depends(_guard)


__all__ = [
    "FakeJWTValidator",
    "JWTValidator",
    "_cognito_jwks_url",
    "require_role",
]
