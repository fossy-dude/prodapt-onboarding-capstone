"""Shared subscriber-identity resolution for subscriber-role endpoints.

Cognito's JWT ``sub`` claim is a Cognito-internal UUID that does NOT equal the
application's ``identity_subscribers.id`` (the true subscriber key stored on
``billing_wallet_balances`` / ``plans_subscriptions`` rows). For phone-provisioned
subscribers the Cognito username — and the ``phone_number`` claim — is the E.164
MSISDN, so the internal subscriber id is resolved from the token's phone number
via :func:`db.identity.queries.get_subscriber_id_by_msisdn`.

Routers import and call :func:`resolve_subscriber_id` inside an open transaction
so the lookup shares the caller's connection. The return type is ``str`` to match
the previous ``_require_sub`` contract (callers do ``UUID(sub_id)`` downstream).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.errors import NotFoundError, UnauthenticatedError
from db.identity.queries import (
    get_subscriber_id_by_cognito_username,
    get_subscriber_id_by_msisdn,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection

# Cognito access tokens carry `username` (= E.164 for phone users); ID tokens
# carry `phone_number` and `cognito:username`. Try all so either token resolves.
_PHONE_CLAIMS = ("phone_number", "username", "cognito:username")


async def resolve_subscriber_id(conn: AsyncConnection, jwt_payload: dict) -> str:
    """Resolve the internal subscriber id (``str`` UUID) from a validated JWT payload.

    Raises :class:`~core.errors.UnauthenticatedError` (401) when the token carries
    no phone-number claim, and :class:`~core.errors.NotFoundError` (404) when the
    phone does not map to a known subscriber (not provisioned in Postgres).
    """
    raw: str | None = None
    for claim in _PHONE_CLAIMS:
        value = jwt_payload.get(claim)
        if value:
            raw = str(value)
            break
    if raw is None:
        raise UnauthenticatedError("Access token carries no subscriber phone number.")

    subscriber_id = await get_subscriber_id_by_msisdn(conn, raw)
    if subscriber_id is None:
        # Fallback: the JWT username may be a Registration ID (pre-activation users)
        # stored as cognito_user_id in identity_subscribers rather than an MSISDN.
        subscriber_id = await get_subscriber_id_by_cognito_username(conn, raw)
    if subscriber_id is None:
        raise NotFoundError("Subscriber not found for token phone number.")
    return str(subscriber_id)


__all__ = ["resolve_subscriber_id"]
