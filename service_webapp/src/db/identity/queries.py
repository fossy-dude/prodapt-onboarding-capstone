"""Read-only DB queries for the identity domain (Story 4.4 USSD).

All functions accept a psycopg ``AsyncConnection``.
Raw SQL via psycopg3; no ORM.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def get_subscriber_by_msisdn(conn: AsyncConnection, msisdn: str) -> dict | None:
    """Return subscriber id and msisdn for a given MSISDN, or ``None`` if not found."""
    cur = await conn.execute(
        """
        SELECT id, msisdn
          FROM identity_subscribers
         WHERE msisdn = %s
         LIMIT 1
        """,
        (msisdn,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "msisdn": row[1]}


async def get_subscriber_id_by_msisdn(conn: AsyncConnection, msisdn: str) -> str | None:
    """Resolve the internal subscriber id (``str``) from any MSISDN form, or ``None``.

    Cognito usernames for phone-provisioned subscribers are E.164 (``+91XXXXXXXXXX``)
    while seeded ``identity_subscribers.msisdn`` rows are ``91XXXXXXXXXX`` (no leading
    ``+``). Accept E.164, ``91``-prefixed, and bare 10-digit national forms by matching
    against both the national and ``91``-prefixed forms.
    """
    digits = re.sub(r"\D", "", msisdn or "")
    if len(digits) < 10:
        return None
    national = digits[-10:]
    cur = await conn.execute(
        """
        SELECT id
          FROM identity_subscribers
         WHERE msisdn IN (%s, %s)
         LIMIT 1
        """,
        (national, f"91{national}"),
    )
    row = await cur.fetchone()
    return str(row[0]) if row is not None else None


async def get_subscriber_id_by_cognito_username(conn: AsyncConnection, username: str) -> str | None:
    """Resolve the internal subscriber id from the cognito_user_id column.

    Covers registration-id-based Cognito users where the Cognito username
    equals the registration_id stored in identity_subscribers.cognito_user_id.
    Returns None when no match is found.
    """
    cur = await conn.execute(
        """
        SELECT id
          FROM identity_subscribers
         WHERE cognito_user_id = %s
         LIMIT 1
        """,
        (username,),
    )
    row = await cur.fetchone()
    return str(row[0]) if row is not None else None


__all__ = [
    "get_subscriber_by_msisdn",
    "get_subscriber_id_by_cognito_username",
    "get_subscriber_id_by_msisdn",
]
