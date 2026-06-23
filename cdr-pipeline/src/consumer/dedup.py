"""Idempotency guard for the CDR consumer (Story 2.2, NFR-9, ARCH-5).

Exactly-once *processing* is achieved by the Valkey ``SET ... NX EX`` guard, not
by Kafka (Kafka is at-least-once). ``dedup:{cdr_id}`` is shared across all
consumers — Valkey is the single source of truth. The atomic ``NX`` is the dedup
decision: if the SET succeeds the event is new; if it fails the ``cdr_id`` was
seen within the 24h window and the event is dropped.

``cdr_id`` is the CDR's own UUIDv7 (the payload ``cdr_id`` / DB PK
``billing_cdr_events.id``) — NOT the envelope ``event_id``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from core.protocols.cache import CacheProtocol

logger = logging.getLogger("consumer.dedup")

# 24-hour dedup window (ARCH-5: dedup:{cdr_id}, TTL 24h).
_DEDUP_TTL_SECONDS = 86400


@dataclass
class DedupStats:
    """In-process dedup metrics, exposed for Story 2.5 / observability."""

    deduplicated: int = 0

    def reset(self) -> None:
        """Zero the counters (used by tests and admin reset flows)."""
        self.deduplicated = 0


# Module-level singleton so Story 2.5's management API can read the live counter
# without DI wiring. A single event loop drives the consumer, so the increment
# needs no lock (no true parallelism within one task).
dedup_stats = DedupStats()


def dedup_key(cdr_id: UUID) -> str:
    """Valkey key for a CDR's idempotency guard (ARCH-5 key domain)."""
    return f"dedup:{cdr_id}"


async def is_duplicate(cache: CacheProtocol, cdr_id: UUID) -> bool:
    """Return ``True`` if ``cdr_id`` was already processed within 24h (duplicate).

    Performs ``SET dedup:{cdr_id} 1 NX EX 86400``: if the key was newly set the
    event is fresh (first sight → returns ``False``); if the SET was rejected
    because the key already existed, the event is a duplicate (→ ``True``) and
    the in-process :data:`dedup_stats` counter is incremented.

    A duplicate is logged at debug with the ``cdr_id`` only — never MSISDN / PII.

    Parameters
    ----------
    cache : CacheProtocol
        Valkey cache providing ``set_nx``.
    cdr_id : UUID
        The CDR's UUIDv7 (not the envelope ``event_id``).
    """
    set_ok = await cache.set_nx(dedup_key(cdr_id), "1", ex=_DEDUP_TTL_SECONDS)
    if set_ok:
        # Freshly set → first sight → not a duplicate.
        return False

    # Key already existed within its TTL → duplicate.
    dedup_stats.deduplicated += 1
    logger.debug("deduplicated cdr_id=%s", cdr_id)
    return True
