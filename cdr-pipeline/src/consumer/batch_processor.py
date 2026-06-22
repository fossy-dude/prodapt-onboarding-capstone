"""CDR batch consumer loop (Story 2.2, Task 4, AC #2/#4/#6).

A single ``AIOKafkaConsumer`` in the ``cdr-balance-updater`` group; a ``getmany``
batch (max 500 records) is processed record-by-record and offsets are committed
ONCE after the whole batch (architecture §1.4.3 — at-least-once delivery +
idempotent dedup). Per record: parse envelope → continue the OTEL trace →
extract ``cdr_id`` → dedup → validate the CDR → forward enriched / route DLQ.

MVP runs a **single consumer task per process** (all 24 ``cdr.raw`` partitions
assigned to it). Scale out by running more process instances — Kafka rebalances
partitions across the group. Do not exceed 24 active consumers (one per
partition). [architecture §1.4.1, §1.7.6]
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from opentelemetry import (
    context as otel_context,
    propagate,
)
from pydantic import TypeAdapter, ValidationError

from consumer.dedup import is_duplicate
from dlq.handler import to_dlq
from models.cdr import CdrEvent
from models.envelope import EventEnvelope

if TYPE_CHECKING:
    from core.protocols.broker import ConsumedRecord, MessageBrokerProtocol, MessageConsumerProtocol
    from core.protocols.cache import CacheProtocol

logger = logging.getLogger("consumer.batch_processor")

RAW_TOPIC = "cdr.raw"
ENRICHED_TOPIC = "cdr.enriched.filtered"
ENRICHED_EVENT_TYPE = "cdr.enriched"

# architecture §1.4.1: batch=500.
BATCH_MAX_RECORDS = 500
# Poll up to 1s for the first record of a batch before yielding the (possibly
# empty) batch and looping — keeps the loop responsive to shutdown signals.
POLL_TIMEOUT_MS = 1000

# Balance-deduction seam implemented by Story 2.3 (consumer/balance_writer.py).
# Default is a no-op so this story ships a runnable consumer without deduction.
BalanceHook = Callable[[CdrEvent], Awaitable[None]]

_CDR_ADAPTER = TypeAdapter(CdrEvent)


async def _noop_balance_hook(_cdr: CdrEvent) -> None:
    """Default balance hook: no-op (Story 2.3 fills this in)."""
    return None


def _extract_cdr_id(raw: object) -> UUID | None:
    """Coerce a payload ``cdr_id`` value to a UUID, or ``None`` if invalid."""
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _attach_trace_context(headers: Sequence[tuple[str, bytes]]):
    """Extract + attach the W3C trace context from Kafka headers (best-effort).

    Returns the OTEL detach token (or ``None`` if no context was attached). A
    malformed ``traceparent`` header is logged and skipped — it must never crash
    record processing. The return type is left implicit so pyrefly infers the
    concrete ``Token | None`` (and the caller's ``is not None`` guard narrows it
    for :func:`opentelemetry.context.detach`).
    """
    header_map = {k: v.decode("utf-8", errors="replace") for k, v in headers}
    if "traceparent" not in header_map:
        return None
    try:
        ctx = propagate.extract(header_map)
    except Exception:
        logger.debug("ignoring malformed traceparent header")
        return None
    return otel_context.attach(ctx)


class BatchProcessor:
    """Drive the consumer loop: getmany → process each → commit after batch.

    Parameters
    ----------
    consumer : MessageConsumerProtocol
        Manual-offset ``aiokafka`` consumer subscribed to ``cdr.raw``.
    producer : MessageBrokerProtocol
        Dual-trace producer for ``cdr.enriched.filtered`` and ``cdr.dlq``.
    cache : CacheProtocol
        Valkey cache backing the dedup guard.
    balance_hook : BalanceHook
        Async balance-deduction callable (Story 2.3 seam); no-op by default.
    """

    def __init__(
        self,
        consumer: MessageConsumerProtocol,
        producer: MessageBrokerProtocol,
        cache: CacheProtocol,
        *,
        balance_hook: BalanceHook | None = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._cache = cache
        self._balance_hook: BalanceHook = balance_hook or _noop_balance_hook
        self._running = False

    async def run(self) -> None:
        """Consume batches until :meth:`stop` is called (graceful shutdown).

        Offsets are committed once per fully-processed batch; a crash mid-batch
        leaves the batch uncommitted → those records are re-delivered and the
        dedup guard absorbs the ones already applied (AC #6).
        """
        self._running = True
        while self._running:
            batch = await self._consumer.getmany(
                max_records=BATCH_MAX_RECORDS,
                timeout_ms=POLL_TIMEOUT_MS,
            )
            if not batch:
                continue
            await self.process_batch(batch)

    async def process_batch(self, batch: Mapping[Any, Sequence[ConsumedRecord]]) -> None:
        """Process every record in ``batch``, then commit offsets once (AC #6).

        Exposed (not just inlined in :meth:`run`) so the per-batch semantics —
        route each record, commit exactly once after the batch — are unit-testable
        without driving the async poll loop.
        """
        for records in batch.values():
            for record in records:
                await self._handle_record(record)
        # Commit the whole batch's offsets together (AC #6: at-least-once + dedup).
        await self._consumer.commit()

    def stop(self) -> None:
        """Signal the loop to exit after the current batch (graceful)."""
        self._running = False

    async def _handle_record(self, record: ConsumedRecord) -> None:
        """Process one record: attach trace context, route, detach."""
        raw_value: bytes = record.value
        raw_key: bytes | None = record.key
        headers: list[tuple[str, bytes]] = list(record.headers or [])

        token = _attach_trace_context(headers)
        try:
            await self._process(raw_value=raw_value, raw_key=raw_key)
        finally:
            if token is not None:
                otel_context.detach(token)

    async def _process(self, *, raw_value: bytes, raw_key: bytes | None) -> None:
        """Route one record: parse → cdr_id → dedup → validate → forward / DLQ."""
        # 1. Parse the envelope. Malformed → DLQ (byte-exact raw, no trace_id).
        try:
            envelope = EventEnvelope.model_validate_json(raw_value)
        except ValidationError:
            await to_dlq(
                self._producer,
                raw_value=raw_value,
                raw_key=raw_key,
                error_reason="envelope_parse_error",
                original_topic=RAW_TOPIC,
            )
            return

        # 2. Extract cdr_id (the mandatory dedup key). Missing/invalid → DLQ.
        cdr_id = _extract_cdr_id(envelope.payload.get("cdr_id"))
        if cdr_id is None:
            await to_dlq(
                self._producer,
                raw_value=raw_value,
                raw_key=raw_key,
                error_reason="missing_or_invalid_cdr_id",
                original_topic=RAW_TOPIC,
                trace_id=envelope.trace_id,
            )
            return

        # 3. Dedup guard (ARCH-5). Duplicate → silently discard (not DLQ).
        if await is_duplicate(self._cache, cdr_id):
            return

        # 4. Validate the CDR payload against the schema. Invalid → DLQ.
        try:
            cdr = _CDR_ADAPTER.validate_python(envelope.payload)
        except ValidationError:
            await to_dlq(
                self._producer,
                raw_value=raw_value,
                raw_key=raw_key,
                error_reason="schema_validation_error",
                original_topic=RAW_TOPIC,
                trace_id=envelope.trace_id,
                cdr_id=cdr_id,
            )
            return

        # 5. Balance-deduction seam (Story 2.3 implements the real hook).
        await self._balance_hook(cdr)

        # 6. Forward the enriched envelope, reusing the incoming trace_id so the
        #    trace survives raw → enriched → (fraud/notification/audit).
        await self._producer.publish(
            ENRICHED_TOPIC,
            key=str(cdr.subscriber_id),
            envelope=EventEnvelope.new(
                event_type=ENRICHED_EVENT_TYPE,
                payload=envelope.payload,
                trace_id=envelope.trace_id,
            ),
        )
