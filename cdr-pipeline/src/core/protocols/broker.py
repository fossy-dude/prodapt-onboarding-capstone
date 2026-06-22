"""Message broker port (architecture §1.12.1 dependency-inversion seam, ARCH-15).

Business logic (consumer, screener, management API) depends on this Protocol,
never the concrete ``aiokafka`` producer — mirroring ``DatabaseProtocol`` /
``CacheProtocol`` (service_webapp ``core/protocols``). All operations are async
(ARCH-15: no blocking I/O in the pipeline).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Annotation-only: the Protocol never instantiates EventEnvelope.
    from models.envelope import EventEnvelope


@runtime_checkable
class MessageBrokerProtocol(Protocol):
    """Async message-broker port: lifecycle + dual-trace-guaranteed publish.

    ``publish`` accepts an :class:`~models.envelope.EventEnvelope` so a caller
    cannot emit a message without a ``trace_id`` (NFR-17): the envelope's
    ``trace_id`` is mandatory, and implementations MUST inject a W3C
    ``traceparent`` header built from it alongside the body ``trace_id``.
    """

    async def start(self) -> None:
        """Connect / initialise the underlying broker client (idempotent)."""
        ...

    async def stop(self) -> None:
        """Flush and close the underlying broker client (idempotent)."""
        ...

    async def publish(self, topic: str, *, key: str, envelope: EventEnvelope) -> None:
        """Serialise ``envelope`` to ``topic`` keyed by ``key`` (UTF-8 bytes).

        Parameters
        ----------
        topic : str
            Destination Kafka topic (must be pre-provisioned).
        key : str
            Partition key — ``subscriber_id`` for ``cdr.raw`` (AC #5),
            ``msisdn`` for fraud/notification topics, ``cdr_id`` for the DLQ.
        envelope : EventEnvelope
            Canonical envelope; its ``trace_id`` populates both the body and
            the injected ``traceparent`` header.
        """
        ...
