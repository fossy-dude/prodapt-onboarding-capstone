"""Standard API response envelopes (architecture §1.11.3; ported from service_webapp, Story 2.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _meta(trace_id: str) -> dict[str, str]:
    return {"trace_id": trace_id, "timestamp": datetime.now(UTC).isoformat()}


def success_envelope(data: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
    """Build the standard success envelope around ``data`` (§1.11.3)."""
    return {"data": data, "meta": _meta(trace_id)}


__all__ = ["success_envelope"]
