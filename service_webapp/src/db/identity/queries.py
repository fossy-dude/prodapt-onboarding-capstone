"""Read-only DB queries for the identity domain (Story 4.4 USSD).

All functions accept a psycopg ``AsyncConnection``.
Raw SQL via psycopg3; no ORM.
"""

from __future__ import annotations

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


__all__ = ["get_subscriber_by_msisdn"]
