"""Dead-letter queue handler (Story 2.2, Task 3, AC #3, ARCH-10).

Routes a failed / unprocessable CDR event to ``cdr.dlq`` with enough metadata
for Story 2.5's DLQ inspector to replay it: the original raw payload
(base64-encoded for byte-exact preservation), the error reason, the originating
topic, and a UTC failure timestamp. The DLQ record is itself wrapped in an
:class:`~models.envelope.EventEnvelope` (``event_type`` ``cdr.dlq``) so trace
continuity is preserved via the dual-trace producer helper.
"""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models.envelope import EventEnvelope

if TYPE_CHECKING:
    # Annotation-only: the handler never instantiates the producer.
    from uuid import UUID

    from core.protocols.broker import MessageBrokerProtocol

DLQ_TOPIC = "cdr.dlq"
DLQ_EVENT_TYPE = "cdr.dlq"


def _fresh_trace_id() -> str:
    """Mint a 32-hex trace id (only when the incoming envelope was unparseable)."""
    return secrets.token_hex(16)


def to_dlq_key(cdr_id: UUID | None, raw_key: bytes | None) -> str | None:
    """Partition key for the DLQ record: ``cdr_id``, else the decoded original key.

    The original ``cdr.raw`` key is the ``subscriber_id``; when ``cdr_id`` could
    not be parsed the DLQ record is still keyed (by subscriber) so related
    failures co-locate. ``None`` only when both are absent (unkeyed).
    """
    if cdr_id is not None:
        return str(cdr_id)
    if raw_key is None:
        return None
    return raw_key.decode("utf-8", errors="replace")


async def to_dlq(
    producer: MessageBrokerProtocol,
    *,
    raw_value: bytes,
    raw_key: bytes | None,
    error_reason: str,
    original_topic: str,
    trace_id: str | None = None,
    cdr_id: UUID | None = None,
) -> None:
    """Publish the original raw event to ``cdr.dlq`` with error metadata (AC #3).

    Parameters
    ----------
    producer : MessageBrokerProtocol
        Dual-trace producer (Story 2.1); injects ``traceparent`` from the
        envelope ``trace_id``.
    raw_value : bytes
        The original, unmodified Kafka message bytes — preserved byte-exact as
        base64 so poison / malformed payloads survive for replay.
    raw_key : bytes | None
        The original message key bytes (``subscriber_id`` for ``cdr.raw``).
    error_reason : str
        Short machine-readable failure reason (e.g. ``"envelope_parse_error"``).
    original_topic : str
        Topic the record was consumed from (``"cdr.raw"``).
    trace_id : str | None
        Incoming trace id to continue; ``None`` if the envelope was unparseable
        (a fresh trace id is minted so the DLQ record still carries one).
    cdr_id : UUID | None
        The CDR id if extractable; used as the DLQ partition key.
    """
    payload = {
        "cdr_id": str(cdr_id) if cdr_id is not None else None,
        "error_reason": error_reason,
        "original_topic": original_topic,
        "failed_at": datetime.now(UTC).isoformat(),
        # base64 preserves the EXACT raw bytes (incl. non-UTF8 poison records).
        "raw_payload_b64": base64.b64encode(raw_value).decode("ascii"),
    }
    envelope = EventEnvelope.new(
        event_type=DLQ_EVENT_TYPE,
        payload=payload,
        trace_id=trace_id if trace_id is not None else _fresh_trace_id(),
    )
    await producer.publish(
        DLQ_TOPIC,
        key=to_dlq_key(cdr_id, raw_key),
        envelope=envelope,
    )
