"""Read CQRS queries for the support domain (Story 5.8).

All functions accept a psycopg ``AsyncConnection`` (from ``db.transaction()``).
Raw SQL via psycopg3 (``%s`` placeholders); no ORM.

The V1 ``support_tickets`` table is a generic ticketing schema; the dispute
payload (``cdr_reference`` / ``charge_paise`` / ``dispute_reason``) lives in the
``description`` TEXT column as JSON, encoded by :mod:`db.support.commands`.
:func:`get_tickets_by_subscriber` decodes it back so the caller sees the AC #4
dispute shape directly.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


def decode_dispute_description(description: str | None) -> dict:
    """Decode the dispute payload stored in ``support_tickets.description``.

    Returns ``{"cdr_reference", "charge_paise", "dispute_reason"}``. On any parse
    failure (a non-dispute ticket, corrupt JSON, NULL) the values degrade to
    empty/zero defaults so the listing never crashes — matching the contract that
    only billing-dispute tickets carry the structured payload.
    """
    if not description:
        return {"cdr_reference": "", "charge_paise": 0, "dispute_reason": ""}
    try:
        payload = json.loads(description)
    except (TypeError, ValueError):
        logger.debug("decode_dispute_description: non-JSON description ignored")
        return {"cdr_reference": "", "charge_paise": 0, "dispute_reason": ""}
    return {
        "cdr_reference": str(payload.get("cdr_reference", "")),
        "charge_paise": int(payload.get("charge_paise", 0) or 0),
        "dispute_reason": str(payload.get("dispute_reason", "")),
    }


async def get_tickets_by_subscriber(
    conn: AsyncConnection,
    subscriber_id: str,
    status: str | None = None,
) -> list[dict]:
    """Return a subscriber's support tickets as the AC #4 dispute shape.

    Rows are ordered newest-first. ``status`` is matched case-insensitively so a
    caller passing ``OPEN`` matches the stored ``open``. Each dict carries
    ``ticket_id``, ``cdr_reference``, ``dispute_reason``, ``status`` and
    ``created_at`` (the dispute values decoded from ``description``).
    """
    sql = """
        SELECT id, description, status, created_at
          FROM support_tickets
         WHERE subscriber_id = %s::uuid
    """
    params: list[str] = [subscriber_id]
    if status is not None and status != "":
        sql += " AND LOWER(status) = LOWER(%s)"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    cur = await conn.execute(sql, tuple(params))
    rows = await cur.fetchall()

    tickets: list[dict] = []
    for row in rows:
        decoded = decode_dispute_description(row[1])
        tickets.append(
            {
                "ticket_id": row[0],
                "cdr_reference": decoded["cdr_reference"],
                "dispute_reason": decoded["dispute_reason"],
                "status": row[2],
                "created_at": row[3],
            }
        )
    return tickets


__all__ = ["decode_dispute_description", "get_tickets_by_subscriber"]
