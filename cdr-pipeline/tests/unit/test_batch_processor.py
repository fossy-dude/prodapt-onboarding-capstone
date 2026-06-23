"""Unit tests for the CDR batch processor (Story 2.2, Task 4/5, AC #1/#2/#3/#6).

Drives :meth:`BatchProcessor.process_batch` directly with a mocked
producer/consumer and a stateful fake cache (mirrors real ``SET NX`` semantics)
so the per-record routing and commit-after-batch semantics are asserted
deterministically — no async poll loop, no live broker.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from consumer.batch_processor import BatchProcessor
from consumer.dedup import dedup_stats
from models.envelope import EventEnvelope

_TRACE_ID = "0123456789abcdef0123456789abcdef"
_SUBSCRIBER = UUID("0192a4d0-1234-7000-8000-000000000abc")
_SESSION = UUID("0192a4d0-abcd-7000-8000-000000000def")
_CDR_IDS = [UUID(f"0192a4d0-0001-7000-8000-00000000000{i}") for i in (1, 2, 3)]
_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TP_HEADER = ("traceparent", f"00-{_TRACE_ID}-0011223344556677-01".encode())


class _FakeCache:
    """In-memory ``SET NX EX`` double: first sight sets, repeat sight is a duplicate."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    async def set_nx(self, key: str, value: str, ex: int) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def seed(self, cdr_id: UUID) -> None:
        """Pre-mark a cdr_id as already seen (simulate a prior delivery)."""
        self._keys.add(f"dedup:{cdr_id}")


class _Rec:
    """Minimal consumed-record double (matches ConsumedRecord)."""

    def __init__(self, value: bytes, key: bytes | None = b"subscriber-1") -> None:
        self.value = value
        self.key = key
        self.headers = [_TP_HEADER]
        self.topic = "cdr.raw"
        self.partition = 0
        self.offset = 0


def _cdr_payload(cdr_id: UUID = _CDR_IDS[0], *, valid: bool = True) -> dict:
    p = {
        "cdr_id": str(cdr_id),
        "session_id": str(_SESSION),
        "subscriber_id": str(_SUBSCRIBER),
        "cdr_type": "sms",
        "telecom_circle": "KA",
        "cost_paise": 25,
        "start_time": _START.isoformat(),
        "message_direction": "MT",
        "sms_status": "delivered",
    }
    if not valid:
        p.pop("cost_paise")  # required field gone → schema validation fails
    return p


def _envelope_bytes(payload: dict, trace_id: str = _TRACE_ID) -> bytes:
    return EventEnvelope.new(event_type="cdr.raw", payload=payload, trace_id=trace_id).model_dump_json().encode()


def _make_processor(*, balance_hook=None):
    """Build a processor wired to a fake cache + mocked consumer/producer."""
    consumer = AsyncMock()
    producer = AsyncMock()
    cache = _FakeCache()
    processor = BatchProcessor(consumer=consumer, producer=producer, cache=cache, balance_hook=balance_hook)
    return processor, producer, cache, consumer


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    dedup_stats.reset()
    yield
    dedup_stats.reset()


# ── AC #2: valid → enriched, trace carried ────────────────────────────────────


async def test_valid_cdr_forwarded_to_enriched_with_trace() -> None:
    processor, producer, _cache, consumer = _make_processor()

    await processor.process_batch({0: [_Rec(_envelope_bytes(_cdr_payload()))]})

    producer.publish.assert_awaited_once()
    args, kwargs = producer.publish.await_args
    assert args[0] == "cdr.enriched.filtered"
    assert kwargs["key"] == str(_SUBSCRIBER)
    env = kwargs["envelope"]
    assert env.event_type == "cdr.enriched"
    assert env.trace_id == _TRACE_ID  # trace_id carried raw → enriched
    consumer.commit.assert_awaited_once()


# ── AC #3: failures → DLQ, raw bytes preserved ────────────────────────────────


async def test_malformed_envelope_routed_to_dlq_byte_exact() -> None:
    processor, producer, _cache, _consumer = _make_processor()
    raw = b"not json at all"

    await processor.process_batch({0: [_Rec(raw)]})

    assert producer.publish.await_count == 1
    args, kwargs = producer.publish.await_args
    assert args[0] == "cdr.dlq"
    payload = kwargs["envelope"].payload
    assert payload["error_reason"] == "envelope_parse_error"
    assert base64.b64decode(payload["raw_payload_b64"]) == raw


async def test_invalid_cdr_schema_routed_to_dlq() -> None:
    processor, producer, _cache, _consumer = _make_processor()

    await processor.process_batch({0: [_Rec(_envelope_bytes(_cdr_payload(valid=False)))]})

    args, kwargs = producer.publish.await_args
    assert args[0] == "cdr.dlq"
    payload = kwargs["envelope"].payload
    assert payload["error_reason"] == "schema_validation_error"
    assert payload["cdr_id"] == str(_CDR_IDS[0])  # cdr_id was extractable
    assert kwargs["key"] == str(_CDR_IDS[0])


async def test_missing_cdr_id_routed_to_dlq() -> None:
    processor, producer, _cache, _consumer = _make_processor()
    payload = _cdr_payload()
    del payload["cdr_id"]

    await processor.process_batch({0: [_Rec(_envelope_bytes(payload))]})

    args, kwargs = producer.publish.await_args
    assert args[0] == "cdr.dlq"
    assert kwargs["envelope"].payload["error_reason"] == "missing_or_invalid_cdr_id"


# ── AC #1: duplicate → discarded (not forwarded, not DLQ) ─────────────────────


async def test_duplicate_discarded_not_forwarded_or_dlqd() -> None:
    processor, producer, cache, consumer = _make_processor()
    cache.seed(_CDR_IDS[0])  # simulate a prior delivery already deduped

    await processor.process_batch({0: [_Rec(_envelope_bytes(_cdr_payload(_CDR_IDS[0])))]})

    producer.publish.assert_not_awaited()  # neither enriched nor DLQ
    assert dedup_stats.deduplicated == 1
    consumer.commit.assert_awaited_once()  # offset still committed after batch


# ── AC #6: commit once after the whole batch ──────────────────────────────────


async def test_batch_commits_once_after_all_records() -> None:
    processor, producer, _cache, consumer = _make_processor()
    batch = {0: [_Rec(_envelope_bytes(_cdr_payload(_CDR_IDS[i]))) for i in range(3)]}

    await processor.process_batch(batch)

    assert producer.publish.await_count == 3  # all three forwarded
    consumer.commit.assert_awaited_once()  # single commit, not per-record


async def test_batch_commits_once_even_with_mixed_outcomes() -> None:
    """Commit is per-batch regardless of per-record routing outcomes."""
    processor, producer, _cache, consumer = _make_processor()
    batch = {
        0: [
            _Rec(_envelope_bytes(_cdr_payload(_CDR_IDS[0]))),  # valid → enriched
            _Rec(b"garbage"),  # malformed → DLQ
            _Rec(_envelope_bytes(_cdr_payload(_CDR_IDS[0]))),  # same cdr_id → duplicate → discard
        ],
    }

    await processor.process_batch(batch)

    # one enriched + one DLQ; the third is a duplicate (no publish)
    assert producer.publish.await_count == 2
    consumer.commit.assert_awaited_once()


# ── Balance-hook seam (Story 2.3) ────────────────────────────────────────────


async def test_balance_hook_called_only_for_valid_first_sight_cdr() -> None:
    hook = AsyncMock()
    processor, _producer, _cache, _consumer = _make_processor(balance_hook=hook)

    await processor.process_batch({0: [_Rec(_envelope_bytes(_cdr_payload()))]})

    hook.assert_awaited_once()
