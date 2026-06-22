"""Unit tests for EventEnvelope model (Story 2.1, AC #3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from models.envelope import EventEnvelope

# Valid 32-hex trace_id for tests
_TRACE_ID = "0123456789abcdef0123456789abcdef"


def test_new_produces_uuidv7_event_id() -> None:
    env = EventEnvelope.new(event_type="cdr.raw", payload={"x": 1}, trace_id=_TRACE_ID)
    # UUIDv7: version nibble is 7 (bits 12-15 of the third group)
    assert env.event_id.version == 7


def test_new_defaults_utc_timestamp() -> None:
    before = datetime.now(UTC)
    env = EventEnvelope.new(event_type="cdr.raw", payload={}, trace_id=_TRACE_ID)
    after = datetime.now(UTC)
    assert before <= env.timestamp <= after
    assert env.timestamp.tzinfo is not None


def test_new_accepts_explicit_event_id_and_timestamp() -> None:
    fixed_id = UUID("0192a4d0-1234-7000-8000-000000000001")
    fixed_ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    env = EventEnvelope.new(
        event_type="cdr.raw",
        payload={},
        trace_id=_TRACE_ID,
        event_id=fixed_id,
        timestamp=fixed_ts,
    )
    assert env.event_id == fixed_id
    assert env.timestamp == fixed_ts


def test_round_trip_json() -> None:
    env = EventEnvelope.new(event_type="cdr.raw", payload={"a": "b"}, trace_id=_TRACE_ID)
    serialised = env.model_dump_json()
    restored = EventEnvelope.model_validate_json(serialised)
    assert restored.event_id == env.event_id
    assert restored.trace_id == env.trace_id
    assert restored.event_type == env.event_type
    assert restored.payload == env.payload


def test_event_id_serialised_as_string() -> None:
    env = EventEnvelope.new(event_type="test", payload={}, trace_id=_TRACE_ID)
    data = json.loads(env.model_dump_json())
    assert isinstance(data["event_id"], str)


def test_timestamp_serialised_as_iso8601_utc() -> None:
    env = EventEnvelope.new(event_type="test", payload={}, trace_id=_TRACE_ID)
    data = json.loads(env.model_dump_json())
    ts_str: str = data["timestamp"]
    # Must be parseable and must carry timezone info
    parsed = datetime.fromisoformat(ts_str)
    assert parsed.tzinfo is not None


def test_trace_id_must_be_32_hex_chars() -> None:
    """EventEnvelope rejects non-32-hex trace_id."""
    with pytest.raises(ValueError, match="32 lowercase hex"):
        EventEnvelope.new(event_type="test", payload={}, trace_id="abc123")
    with pytest.raises(ValueError, match="32 lowercase hex"):
        EventEnvelope.new(event_type="test", payload={}, trace_id="0123456789abcdef0123456789abcdefg")


def test_timestamp_must_be_timezone_aware() -> None:
    """EventEnvelope rejects naive datetimes (would be silently treated as local time)."""
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope.new(
            event_type="test",
            payload={},
            trace_id=_TRACE_ID,
            timestamp=datetime(2026, 1, 1, 12, 0, 0),  # naive — no tzinfo
        )


def test_payload_rejects_non_json_types() -> None:
    """EventEnvelope rejects non-JSON-serializable types (bytes, set, etc.)."""
    import pydantic

    # bytes silently stringified (data loss)
    with pytest.raises(pydantic.ValidationError):
        EventEnvelope.new(event_type="test", payload={"raw": b"hello"}, trace_id=_TRACE_ID)

    # set loses ordering
    with pytest.raises(pydantic.ValidationError):
        EventEnvelope.new(event_type="test", payload={"tags": {1, 2, 3}}, trace_id=_TRACE_ID)
