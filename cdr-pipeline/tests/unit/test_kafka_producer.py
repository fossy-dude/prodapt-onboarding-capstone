"""Unit tests for the Kafka producer helper (Story 2.1, AC #4, #5).

No live broker: ``AIOKafkaProducer`` is mocked. The dual-trace rule (NFR-17) is
the high-value assertion — both a ``traceparent`` header AND a body ``trace_id``
must ride on every message, and the key must be the subscriber id bytes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from adapters.kafka import KafkaProducer, build_traceparent
from models.envelope import EventEnvelope

_TRACE_ID = "0123456789abcdef0123456789abcdef"  # 32 hex chars (W3C trace-id)


def test_build_traceparent_is_w3c_shaped() -> None:
    tp = build_traceparent(_TRACE_ID)
    parts = tp.split("-")
    assert len(parts) == 4
    assert parts[0] == "00"  # version
    assert parts[1] == _TRACE_ID  # trace-id
    assert len(parts[2]) == 16  # span-id (parent-id), 16 hex
    int(parts[2], 16)  # parses as hex
    assert parts[3] == "01"  # sampled flag


async def test_publish_sets_dual_trace_and_key(mocker: pytest.MockerFixture) -> None:
    """AC #4/#5: header traceparent + body trace_id + key=subscriber_id bytes."""
    mock_instance = AsyncMock()
    mock_class = mocker.patch("adapters.kafka.AIOKafkaProducer", return_value=mock_instance)

    producer = KafkaProducer(bootstrap_servers="localhost:9092")
    await producer.start()
    mock_class.assert_called_once_with(bootstrap_servers="localhost:9092")
    mock_instance.start.assert_awaited_once()

    envelope = EventEnvelope.new(event_type="cdr.raw", payload={"x": 1}, trace_id=_TRACE_ID)
    await producer.publish("cdr.raw", key="subscriber-123", envelope=envelope)

    mock_instance.send_and_wait.assert_awaited_once()
    call = mock_instance.send_and_wait.await_args
    args, kwargs = call.args, call.kwargs

    # AC #5: key is the subscriber_id as UTF-8 bytes.
    assert kwargs["key"] == b"subscriber-123"
    assert args[0] == "cdr.raw"  # topic is positional

    # AC #4: traceparent header built from the envelope's trace_id.
    headers = dict(kwargs["headers"])
    assert "traceparent" in headers
    tp = headers["traceparent"].decode("utf-8")
    assert tp.split("-")[1] == _TRACE_ID

    # AC #4: body carries trace_id too (dual propagation).
    body = json.loads(kwargs["value"])
    assert body["trace_id"] == _TRACE_ID
    assert body["event_type"] == "cdr.raw"


async def test_publish_requires_start(mocker: pytest.MockerFixture) -> None:
    """Calling publish before start() raises, so no message is emitted unconfigured."""
    mocker.patch("adapters.kafka.AIOKafkaProducer")
    producer = KafkaProducer(bootstrap_servers="localhost:9092")
    envelope = EventEnvelope.new(event_type="cdr.raw", payload={}, trace_id=_TRACE_ID)
    with pytest.raises(RuntimeError, match="start"):
        await producer.publish("cdr.raw", key="s", envelope=envelope)


async def test_stop_is_idempotent(mocker: pytest.MockerFixture) -> None:
    mocker.patch("adapters.kafka.AIOKafkaProducer")
    producer = KafkaProducer(bootstrap_servers="localhost:9092")
    await producer.stop()  # never started — must not raise


def test_kafka_producer_satisfies_protocol(mocker: pytest.MockerFixture) -> None:
    """KafkaProducer is a structural match for MessageBrokerProtocol (DI seam)."""
    from core.protocols.broker import MessageBrokerProtocol

    mocker.patch("adapters.kafka.AIOKafkaProducer")
    assert isinstance(KafkaProducer(bootstrap_servers="localhost:9092"), MessageBrokerProtocol)
