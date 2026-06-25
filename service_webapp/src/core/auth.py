"""JWT validation + role-based access guard (Story 1.8; §1.8.1, §1.8.2, NFR-7).

Validates Cognito-issued access tokens via JWKS (RS256). Roles arrive as the
``cognito:groups`` claim — NOT a ``role`` custom attribute (which would only land
in the ID token; architecture §1.8.1 + provision_cognito.py comment). PII hygiene:
only ``sub`` (UUID) and ``msisdn[-4:]`` may appear in logs/spans — never the raw
MSISDN, name, or token internals.

Usage in a route::

    from core.auth import require_role


    @router.get("/subscriber/profile")
    async def profile(payload: dict = require_role("subscriber")):
        sub_id = payload["sub"]
        ...

Error envelopes follow §1.11.3 via the :class:`~core.errors.UnauthenticatedError`
/ :class:`~core.errors.ForbiddenError` domain-error hierarchy registered in
:func:`~core.errors.register_exception_handlers`.
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
    """Build the Cognito JWKS URL for the provisioned user pool."""
    return (
        f"{settings.cognito_endpoint_url}"
        f"/{settings.cognito_region}"
        f"/{settings.cognito_user_pool_id}"
        f"/.well-known/jwks.json"
    )


class JWTValidator:
    """Validate Cognito RS256 access tokens via the user pool's JWKS endpoint.

    ``PyJWT`` is imported lazily so importing this module at test collection time
    does not require the library to be installed in lightweight envs.

    When *dev_mode* is True (LocalStack / CI), signature verification is skipped
    because LocalStack Community does not serve the JWKS endpoint. Claims (expiry,
    groups, sub) are still decoded and checked; only the RS256 signature is trusted
    implicitly. Never enable in production.
    """

    def __init__(self, jwks_url: str, *, dev_mode: bool = False) -> None:
        self._jwks_url = jwks_url
        self._dev_mode = dev_mode
        self._jwks_client: Any = None  # jwt.PyJWKClient — initialised lazily

    def _client(self) -> Any:
        if self._jwks_client is None:
            import jwt  # noqa: PLC0415 — lazy; avoids hard dep at collection time

            self._jwks_client = jwt.PyJWKClient(self._jwks_url, cache_keys=True)
        return self._jwks_client

    def decode(self, token: str) -> dict[str, Any]:
        """Decode ``token``, verify RS256 signature + expiry, return payload dict.

        Raises :class:`~core.errors.UnauthenticatedError` for any failure — never
        leaks token internals in the error message.
        """
        import jwt  # noqa: PLC0415

        if self._dev_mode:
            # LocalStack Community does not implement the Cognito JWKS endpoint.
            # Decode without signature verification; expiry is still enforced.
            logger.warning("JWT validation: dev mode active — RS256 signature not verified")
            try:
                return jwt.decode(
                    token,
                    algorithms=["RS256"],
                    options={"verify_signature": False, "verify_exp": True, "verify_aud": False},
                )
            except jwt.ExpiredSignatureError as exc:
                logger.info("JWT validation: token expired")
                raise UnauthenticatedError("Access token has expired.") from exc
            except jwt.InvalidTokenError as exc:
                logger.info("JWT validation: invalid token (%s)", type(exc).__name__)
                raise UnauthenticatedError("Access token is invalid.") from exc

        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},  # Cognito access tokens have no aud claim
            )
        except jwt.ExpiredSignatureError as exc:
            logger.info("JWT validation: token expired")
            raise UnauthenticatedError("Access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            logger.info("JWT validation: invalid token (%s)", type(exc).__name__)
            raise UnauthenticatedError("Access token is invalid.") from exc
        except Exception as exc:
            # P13: JWKS fetch or network failure — surface as 401, not 500.
            logger.warning("JWT validation: JWKS/network error (%s)", type(exc).__name__)
            raise UnauthenticatedError("Token validation temporarily unavailable.") from exc


class FakeJWTValidator:
    """Deterministic in-memory JWT validator for unit tests.

    Injects a fixed payload without needing RSA keys or a JWKS endpoint.
    Set ``fail`` to ``"expired"`` or ``"invalid"`` to simulate failures.
    """

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
    # P14: "Bearer " with no trailing token → empty string → reject immediately.
    if not token:
        raise UnauthenticatedError("Missing or malformed Authorization header.")
    return token


def require_role(*roles: str) -> Any:
    """Return a FastAPI ``Depends`` that validates the Bearer JWT and checks ``cognito:groups``.

    Parameters
    ----------
    *roles:
        Group names the caller must belong to (from ``cognito:groups``). An empty
        call (``require_role()``) validates the token without a group check —
        any authenticated user is allowed.

    Raises
    ------
    UnauthenticatedError
        Missing/invalid/expired token → 401.
    ForbiddenError
        Valid token but caller is not in any of the required groups → 403.

    Returns
    -------
    dict
        Decoded JWT payload dict — ``sub``, ``cognito:groups``, etc.
    """

    async def _guard(request: Request) -> dict[str, Any]:
        validator = getattr(request.app.state, "jwt_validator", None)
        if validator is None:
            # Fail loudly in dev; should never happen in production if main.py wires
            # app.state.jwt_validator during the lifespan.
            raise RuntimeError("jwt_validator not wired onto app.state — check lifespan")

        token = _extract_token(request)
        payload = validator.decode(token)  # raises UnauthenticatedError on failure

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
    "require_role",
]
