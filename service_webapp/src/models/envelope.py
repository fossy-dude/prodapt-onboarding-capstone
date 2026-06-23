"""Kafka event envelope for service_webapp CDR producer (Story 2.8, ARCH-11).

Mirrors ``cdr-pipeline/src/models/envelope.py`` byte-for-byte.
DUPLICATION NOTE: Two-codebase rule (architecture §1.5.1) forbids a shared package;
these models are kept in sync by contract — any change to one must propagate to the
other manually until a future shared module consolidates them.

Dual trace propagation rule (NFR-17): ``trace_id`` lives in the JSON body AND a W3C
``traceparent`` header is set on the Kafka message by the producer helper.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID  # noqa: TC003  # pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_serializer
from uuid_extensions import uuid7


def _reject_non_json_types(v: Any) -> Any:
    """Walk a dict and reject non-JSON-native types (bytes, set, etc.)."""
    if isinstance(v, dict):
        return {k: _reject_non_json_types(item) for k, item in v.items()}
    if isinstance(v, list):
        return [_reject_non_json_types(item) for item in v]
    if isinstance(v, (bytes, set, frozenset, bytearray)):
        raise ValueError(f"Non-JSON-serializable type {type(v).__name__} not allowed in payload")
    return v


class EventEnvelope(BaseModel):
    """Shared event envelope for all CDR pipeline Kafka messages."""

    model_config = ConfigDict(populate_by_name=True)

    event_type: str
    event_id: UUID
    trace_id: str = Field(
        ...,
        pattern=r"^[0-9a-f]{32}$",
        description="W3C trace-id (32 lowercase hex chars).",
    )
    timestamp: datetime
    payload: dict[str, Any]

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (use datetime.now(UTC) or pass tzinfo)")
        return v

    @field_validator("payload")
    @classmethod
    def _payload_must_be_json_serializable(cls, v: dict[str, Any]) -> dict[str, Any]:
        _reject_non_json_types(v)
        return v

    @field_serializer("event_id")
    def _serialise_event_id(self, v: UUID) -> str:
        return str(v)

    @field_serializer("timestamp")
    def _serialise_timestamp(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat()

    @classmethod
    def new(
        cls,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str,
        *,
        event_id: UUID | None = None,
        timestamp: datetime | None = None,
    ) -> EventEnvelope:
        """Create a new envelope with sensible defaults."""
        return cls(
            event_type=event_type,
            event_id=event_id if event_id is not None else cast("UUID", uuid7()),
            trace_id=trace_id,
            timestamp=timestamp if timestamp is not None else datetime.now(UTC),
            payload=payload,
        )


__all__ = ["EventEnvelope"]
