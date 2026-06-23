"""Standard API response envelopes (architecture §1.11.3; Story 1.6).

Success envelope::

    {"data": {...}, "meta": {"trace_id": "...", "timestamp": "..."}}

Error envelopes live in :mod:`core.errors`. The trace id is sourced from the
OTEL trace middleware (``request.state.trace_id``); the timestamp is ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _meta(trace_id: str) -> dict[str, str]:
    return {"trace_id": trace_id, "timestamp": datetime.now(UTC).isoformat()}


def success_envelope(data: Any, *, trace_id: str) -> dict[str, Any]:
    """Build the standard success envelope around ``data`` (§1.11.3)."""
    return {"data": data, "meta": _meta(trace_id)}


__all__ = ["success_envelope"]
