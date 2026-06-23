"""Canonical Kafka event envelope for all CDR pipeline messages (Story 2.1, ARCH-11).

Every message published to any CDR pipeline topic MUST use this envelope.
Dual trace propagation rule (NFR-17): `trace_id` lives in the JSON body AND
a W3C `traceparent` header is set on the Kafka message by the producer helper.
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
        # ValueError (not TypeError) so pydantic wraps it into a ValidationError,
        # consistent with the rest of the field validators.
        raise ValueError(f"Non-JSON-serializable type {type(v).__name__} not allowed in payload")
    return v


class EventEnvelope(BaseModel):
    """Shared event envelope for all CDR pipeline Kafka messages.

    Parameters
    ----------
    event_type : str
        Dot-separated event name, e.g. ``"cdr.raw"``.
    event_id : UUID
        UUIDv7 unique message identifier (time-ordered).
    trace_id : str
        W3C trace-id (32 hex chars) propagated from the originating request.
    timestamp : datetime
        UTC event time (timezone-aware).
    payload : dict[str, Any]
        Arbitrary event payload; consumers validate against their own schema.
    """

    model_config = ConfigDict(populate_by_name=True)

    event_type: str
    event_id: UUID
    trace_id: str = Field(
        ...,
        # Anchored (full-match): pydantic ``pattern`` matches partially by default,
        # so without ``^...$`` a 33-char string containing 32 hex chars would pass.
        pattern=r"^[0-9a-f]{32}$",
        description="W3C trace-id (32 lowercase hex chars).",
    )
    timestamp: datetime
    payload: dict[str, Any]

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_tz_aware(cls, v: datetime) -> datetime:
        """Reject naive datetimes — they would be silently interpreted as local time."""
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (use datetime.now(UTC) or pass tzinfo)")
        return v

    @field_validator("payload")
    @classmethod
    def _payload_must_be_json_serializable(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject non-JSON-native types (bytes, set, etc.) that corrupt on serialization."""
        _reject_non_json_types(v)
        return v

    @field_serializer("event_id")
    def _serialise_event_id(self, v: UUID) -> str:
        return str(v)

    @field_serializer("timestamp")
    def _serialise_timestamp(self, v: datetime) -> str:
        # Force UTC and emit ISO-8601 (produces +00:00, not Z suffix).
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
        """Create a new envelope with sensible defaults.

        Parameters
        ----------
        event_type : str
            Dot-separated event name.
        payload : dict[str, Any]
            Arbitrary event payload.
        trace_id : str
            W3C trace-id from the originating request context.
        event_id : UUID | None
            Override the generated UUIDv7; useful in tests.
        timestamp : datetime | None
            Override the current UTC timestamp; useful in tests.
        """
        return cls(
            event_type=event_type,
            # uuid7() returns a UUID at runtime (default as_type=None); its stub is
            # the broad Union[UUID, str, int, bytes], so cast for the type checker.
            event_id=event_id if event_id is not None else cast("UUID", uuid7()),
            trace_id=trace_id,
            timestamp=timestamp if timestamp is not None else datetime.now(UTC),
            payload=payload,
        )
