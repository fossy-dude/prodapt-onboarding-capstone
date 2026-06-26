"""Standard API response envelopes (architecture §1.11.3; Story 1.6).

Success envelope::

    {"data": {...}, "meta": {"trace_id": "...", "timestamp": "..."}}

Error envelopes live in :mod:`core.errors`. The trace id is sourced from the
OTEL trace middleware (``request.state.trace_id``); the timestamp is ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Sentinel distinguishing "next_cursor not provided" from "next_cursor=None".
# Existing endpoints never pass next_cursor, so their ``meta`` is unchanged; only
# paginated endpoints (e.g. GET /transactions, Story 3.3) opt in.
_NOT_GIVEN: Any = object()


def _meta(trace_id: str, next_cursor: Any = _NOT_GIVEN) -> dict[str, Any]:
    meta: dict[str, Any] = {"trace_id": trace_id, "timestamp": datetime.now(UTC).isoformat()}
    if next_cursor is not _NOT_GIVEN:
        meta["next_cursor"] = next_cursor
    return meta


def success_envelope(data: Any, *, trace_id: str, next_cursor: Any = _NOT_GIVEN) -> dict[str, Any]:
    """Build the standard success envelope around ``data`` (§1.11.3).

    ``next_cursor`` is optional: omit it (the default) for non-paginated responses
    and ``meta`` stays ``{trace_id, timestamp}``. Paginated endpoints pass it
    explicitly (a cursor string or ``None`` when exhausted) so ``meta`` carries a
    ``next_cursor`` key for the client.
    """
    return {"data": data, "meta": _meta(trace_id, next_cursor)}


__all__ = ["success_envelope"]
