"""Unit tests for the DLQ handler (Story 2.2, Task 3, AC #3).

Producer is mocked; the high-value assertions are the DLQ topic/key, the error
metadata shape, byte-exact raw preservation (base64), and trace continuity.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import UUID

from dlq.handler import DLQ_EVENT_TYPE, DLQ_TOPIC, to_dlq, to_dlq_key

if TYPE_CHECKING:
    from models.envelope import EventEnvelope

_TRACE_ID = "0123456789abcdef0123456789abcdef"
_CDR_ID = UUID("0192a4d0-0001-7000-8000-000000000001")
_RAW = b'{"not valid json"'


def test_to_dlq_key_prefers_cdr_id() -> None:
    assert to_dlq_key(_CDR_ID, b"subscriber-1") == str(_CDR_ID)


def test_to_dlq_key_falls_back_to_decoded_raw_key() -> None:
    assert to_dlq_key(None, b"subscriber-1") == "subscriber-1"


def test_to_dlq_key_none_when_both_absent() -> None:
    assert to_dlq_key(None, None) is None


async def test_to_dlq_publishes_raw_bytes_base64_with_metadata() -> None:
    producer = AsyncMock()

    await to_dlq(
        producer,
        raw_value=_RAW,
        raw_key=b"subscriber-1",
        error_reason="envelope_parse_error",
        original_topic="cdr.raw",
        trace_id=_TRACE_ID,
        cdr_id=_CDR_ID,
    )

    producer.publish.assert_awaited_once()
    args, kwargs = producer.publish.await_args
    assert args[0] == DLQ_TOPIC
    assert kwargs["key"] == str(_CDR_ID)

    envelope: EventEnvelope = kwargs["envelope"]
    assert envelope.event_type == DLQ_EVENT_TYPE
    assert envelope.trace_id == _TRACE_ID  # trace continued
    payload = envelope.payload
    assert payload["cdr_id"] == str(_CDR_ID)
    assert payload["error_reason"] == "envelope_parse_error"
    assert payload["original_topic"] == "cdr.raw"
    assert "failed_at" in payload
    # Byte-exact preservation: base64 decodes back to the original raw bytes.
    assert base64.b64decode(payload["raw_payload_b64"]) == _RAW


async def test_to_dlq_mints_fresh_trace_id_when_none() -> None:
    """Unparseable envelope → no trace_id → a fresh one is minted for the DLQ record."""
    producer = AsyncMock()

    await to_dlq(
        producer,
        raw_value=_RAW,
        raw_key=None,
        error_reason="envelope_parse_error",
        original_topic="cdr.raw",
        trace_id=None,
        cdr_id=None,
    )

    envelope = producer.publish.await_args.kwargs["envelope"]
    assert len(envelope.trace_id) == 32
    int(envelope.trace_id, 16)  # valid hex
    # No cdr_id and no raw_key → unkeyed.
    assert producer.publish.await_args.kwargs["key"] is None


async def test_to_dlq_envelope_serialises_with_poison_bytes() -> None:
    """The DLQ envelope must JSON-serialise even for non-UTF8 poison payloads."""
    producer = AsyncMock()
    await to_dlq(
        producer,
        raw_value=b"\x00\x01\x02\xff",  # non-UTF8 poison bytes
        raw_key=b"k",
        error_reason="bad",
        original_topic="cdr.raw",
    )
    envelope = producer.publish.await_args.kwargs["envelope"]
    # Round-trips through JSON without raising (the producer serialises this way).
    data = json.loads(envelope.model_dump_json())
    assert data["payload"]["raw_payload_b64"]
