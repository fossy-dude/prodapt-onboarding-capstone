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

import secrets
from typing import TYPE_CHECKING

from aiokafka import AIOKafkaProducer

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
    """
    span_id = secrets.token_hex(8)  # 16 hex chars, never all-zero in practice.
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

    async def start(self) -> None:
        """Create and start the underlying ``AIOKafkaProducer`` (idempotent)."""
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

    async def publish(self, topic: str, *, key: str, envelope: EventEnvelope) -> None:
        """Publish ``envelope`` to ``topic``, keyed by ``key`` (AC #4, AC #5).

        Raises
        ------
        RuntimeError
            If :meth:`start` has not been called.
        """
        if self._producer is None:
            msg = "KafkaProducer.publish called before start(); call start() first."
            raise RuntimeError(msg)

        value = envelope.model_dump_json().encode("utf-8")
        traceparent = build_traceparent(envelope.trace_id).encode("utf-8")
        await self._producer.send_and_wait(
            topic,
            value=value,
            key=key.encode("utf-8"),
            headers=[("traceparent", traceparent)],
        )
