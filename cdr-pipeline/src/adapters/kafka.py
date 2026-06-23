"""Async Kafka producer adapter with W3C dual-trace propagation (Story 2.1, AC #4/#5).

Wraps :class:`aiokafka.AIOKafkaProducer` and implements
:class:`~core.protocols.broker.MessageBrokerProtocol`. Every published message
carries the trace **twice** (NFR-17): a W3C ``traceparent`` entry in the Kafka
message **headers** AND ``trace_id`` in the JSON **body** (the envelope itself).
The partition ``key`` is the caller-supplied string (``subscriber_id`` for
``cdr.raw`` — AC #5), encoded as UTF-8 bytes so all events for one subscriber
land on the same partition.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from typing import TYPE_CHECKING

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from core.config import settings
from core.protocols.broker import MessageBrokerProtocol

if TYPE_CHECKING:
    # Annotation-only: publish receives an EventEnvelope instance, never builds one.
    from models.envelope import EventEnvelope

# W3C traceparent: ``version-trace_id-parent_id-trace_flags``.
# version=00, trace_id=<32 hex>, parent_id(span)=<16 hex>, flags=01 (sampled).
_TRACEPARENT_TEMPLATE = "00-{trace_id}-{span_id}-01"


def build_traceparent(trace_id: str) -> str:
    """Build a W3C ``traceparent`` header value from a 32-hex ``trace_id``.

    The envelope only carries ``trace_id``; the per-message ``span_id`` (16 hex)
    is generated here so the header is well-formed for
    ``opentelemetry.propagate.extract(headers)`` on the consumer side (Story 2.2).

    Raises
    ------
    ValueError
        If ``trace_id`` is not exactly 32 lowercase hex characters.
    """
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise ValueError(f"trace_id must be 32 lowercase hex chars, got: {trace_id}")

    # W3C forbids all-zero span_id; retry until we get a non-zero value.
    while True:
        span_id = secrets.token_hex(8)  # 16 hex chars
        if span_id != "0" * 16:
            break
    return _TRACEPARENT_TEMPLATE.format(trace_id=trace_id, span_id=span_id)


class KafkaProducer(MessageBrokerProtocol):
    """Async Kafka producer backed by ``aiokafka``.

    Parameters
    ----------
    bootstrap_servers : str | None
        Comma-separated broker list. Defaults to ``settings.kafka_brokers``
        (the eager config singleton) so callers need not thread it through.
    """

    def __init__(self, *, bootstrap_servers: str | None = None) -> None:
        self._bootstrap_servers = bootstrap_servers or settings.kafka_brokers
        self._producer: AIOKafkaProducer | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        """Create and start the underlying ``AIOKafkaProducer`` (idempotent)."""
        async with self._start_lock:
            if self._producer is not None:
                return
            self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
            await self._producer.start()

    async def stop(self) -> None:
        """Stop and drop the underlying producer (idempotent)."""
        if self._producer is None:
            return
        await self._producer.stop()
        self._producer = None

    async def publish(self, topic: str, *, key: str | None, envelope: EventEnvelope) -> None:
        """Publish ``envelope`` to ``topic``, keyed by ``key`` (AC #4, AC #5).

        Parameters
        ----------
        topic : str
            Destination Kafka topic.
        key : str | None
            Partition key (e.g., ``subscriber_id``). ``None`` means unkeyed (no partitioning).
        envelope : EventEnvelope
            Canonical envelope; its ``trace_id`` populates both body and header.

        Raises
        ------
        RuntimeError
            If :meth:`start` has not been called.
        ValueError
            If ``key`` is not a string when provided (i.e., ``None`` was passed).
        """
        if self._producer is None:
            msg = "KafkaProducer.publish called before start(); call start() first."
            raise RuntimeError(msg)

        if key is not None and not isinstance(key, str):
            raise ValueError(f"key must be str or None, got {type(key).__name__}")

        value = envelope.model_dump_json().encode("utf-8")
        traceparent = build_traceparent(envelope.trace_id).encode("utf-8")
        await self._producer.send_and_wait(
            topic,
            value=value,
            key=key.encode("utf-8") if key is not None else None,
            headers=[("traceparent", traceparent)],
        )


def build_consumer(
    *topics: str,
    group_id: str,
    bootstrap_servers: str | None = None,
) -> AIOKafkaConsumer:
    """Construct an ``AIOKafkaConsumer`` for the CDR pipeline (Story 2.2, AC #4).

    Manual offset management (``enable_auto_commit=False``) with
    ``auto_offset_reset="earliest"`` so a fresh group replays the backlog;
    commits happen once per fully-processed batch (architecture §1.4.3 —
    at-least-once delivery absorbed by the Valkey dedup guard). No value/key
    deserialiser: records arrive as raw bytes so malformed/poison payloads reach
    the DLQ byte-exact (AC #3) and the envelope is parsed explicitly in
    :mod:`consumer.batch_processor`.

    Parameters
    ----------
    *topics : str
        Topics to subscribe to (e.g. ``"cdr.raw"``).
    group_id : str
        Consumer-group id (``settings.kafka_consumer_groups.balance_updater``
        for the CDR consumer — distinct per logical consumer).
    bootstrap_servers : str | None
        Comma-separated broker list; defaults to ``settings.kafka_brokers``.
    """
    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers or settings.kafka_brokers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
