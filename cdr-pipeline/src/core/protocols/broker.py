"""Message broker ports (architecture §1.12.1 dependency-inversion seam, ARCH-15).

Business logic (consumer, screener, management API) depends on these Protocols,
never the concrete ``aiokafka`` producer/consumer — mirroring ``DatabaseProtocol``
/ ``CacheProtocol`` (service_webapp ``core/protocols``). All operations are async
(ARCH-15: no blocking I/O in the pipeline).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Annotation-only: the Protocols never instantiate EventEnvelope.
    from collections.abc import Mapping, Sequence

    from models.envelope import EventEnvelope


class ConsumedRecord(Protocol):
    """Minimal shape of a consumed Kafka record (duck-typed for DI / tests).

    Matches :class:`aiokafka.structs.ConsumerRecord` on the fields the batch
    processor actually reads. ``value``/``key`` are raw bytes (no deserialiser)
    so poison payloads reach the DLQ byte-exact (Story 2.2 AC #3).
    """

    value: bytes
    key: bytes | None
    headers: Sequence[tuple[str, bytes]]
    topic: str
    partition: int
    offset: int


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

    async def publish(self, topic: str, *, key: str | None, envelope: EventEnvelope) -> None:
        """Serialise ``envelope`` to ``topic`` keyed by ``key`` (UTF-8 bytes, or ``None`` for unkeyed).

        Parameters
        ----------
        topic : str
            Destination Kafka topic (must be pre-provisioned).
        key : str | None
            Partition key — ``subscriber_id`` for ``cdr.raw`` (AC #5),
            ``msisdn`` for fraud/notification topics, ``cdr_id`` for the DLQ,
            or ``None`` for unkeyed messages (no partitioning).
        envelope : EventEnvelope
            Canonical envelope; its ``trace_id`` populates both the body and
            the injected ``traceparent`` header.
        """
        ...


@runtime_checkable
class MessageConsumerProtocol(Protocol):
    """Async message-consumer port: manual-offset batch consume + commit.

    The batch processor (Story 2.2) drives a consumer through this port:
    ``getmany`` returns a batch, records are processed, then ``commit`` is
    called **once after the batch** (architecture §1.4.3 — at-least-once
    delivery + idempotent dedup). ``enable_auto_commit=False`` is mandated.
    """

    async def start(self) -> None:
        """Join the group and begin partition assignment (idempotent)."""
        ...

    async def getmany(self, *, max_records: int, timeout_ms: int) -> Mapping[Any, Sequence[ConsumedRecord]]:
        """Fetch up to ``max_records`` records across the assigned partitions.

        Returns a mapping of partition → records; blocks up to ``timeout_ms``
        for the first record and returns an empty mapping on timeout.
        """
        ...

    async def commit(self) -> None:
        """Commit offsets for the consumed positions (manual, after the batch)."""
        ...

    async def stop(self) -> None:
        """Leave the group and close the consumer (idempotent)."""
        ...
