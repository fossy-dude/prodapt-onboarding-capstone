"""Balance writer hot path + async flusher (Story 2.3, Task 1/4/5/6).

Hot path (``deduct``): on a first-sight CDR (dedup already enforced by Story 2.2),
resolve the subscriber's ``msisdn`` via the in-process index, atomically ``INCRBY
balance:{msisdn} -cost_paise`` (negative deduction), mark the msisdn dirty, and
enqueue a ledger row (``billing_transactions`` insert). Emits an OTEL span.
Operates O(1) with zero blocking I/O — the ``INCRBY`` is the P95 ≤ 200ms gate.

Async flusher: loops on a configurable 2s / 5000 dirty keys trigger, reads current
``balance:{msisdn}`` values from Valkey, bulk-upserts ``billing_wallet_balances``,
and batch-inserts the queued ledger rows. Runs in a background task; on shutdown,
flushes once more. Keys are never deleted (they remain the live buffer).

Idempotency: the batch processor (Story 2.2) guarantees the hook is called only
on first-sight events, so deduction is idempotent by construction. This engine
does NOT add a second dedup guard (Dev Notes).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import trace

from consumer.startup import load_balances_from_postgres

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol
    from models.cdr import CdrEvent

logger = logging.getLogger("consumer.balance_writer")

tracer = trace.get_tracer(__name__)

# Bulk upsert: ON CONFLICT (msisdn) keeps the wallet row in sync with the live
# Valkey buffer. subscriber_id is supplied so a genuinely new msisdn inserts too.
_BALLED_UPSERT_SQL = """\
INSERT INTO billing_wallet_balances (
    id, subscriber_id, msisdn, balance_paise, last_deduction_at, created_at, modified_at
) VALUES (
    gen_random_uuid(),
    $1,
    $2,
    $3,
    NOW(),
    NOW(),
    NOW()
)
ON CONFLICT (msisdn)
DO UPDATE SET
    balance_paise = EXCLUDED.balance_paise,
    last_deduction_at = NOW(),
    modified_at = NOW()
"""

# Append-only forensic ledger (one row per first-sight deduction). amount_paise
# is negative for a deduction; balance_before/after capture the atomic transition.
_LEDGER_INSERT_SQL = """\
INSERT INTO billing_transactions (
    id, subscriber_id, transaction_type, amount_paise, reference_type, reference_id,
    description, balance_before_paise, balance_after_paise, created_at
) VALUES (
    uuid_generate_v7(),
    $1,
    'cdr_deduction',
    $2,
    'cdr',
    $3,
    $4,
    $5,
    $6,
    NOW()
)
"""


@dataclass(slots=True)
class LedgerRow:
    """Queued ledger row for batch insert (flush-adjacent async path)."""

    subscriber_id: str  # UUID string
    amount_paise: int  # negative for deduction
    cdr_id: str  # UUID string
    description: str
    balance_before: int
    balance_after: int


class BalanceEngine:
    """Hot-path balance writer + async flusher.

    Plain class (not a dataclass) so the mutable in-process state (dirty set,
    ledger queue, indices) is initialised in ``__init__`` — a manual ``__init__``
    on a ``@dataclass`` would silently skip the ``field(default_factory=...)``
    defaults and leave those attributes unset.

    Parameters
    ----------
    cache : CacheProtocol
        Valkey cache providing ``incr_by`` (hot path) and ``get_str`` (flusher).
    db : DatabaseProtocol
        Postgres adapter with a ``transaction`` context manager (flusher upserts
        + ledger inserts, warm-up query).
    flush_interval : float
        Seconds between timed flushes (default 2s, AC #3).
    flush_dirty_threshold : int
        Dirty-msisdn count that triggers an early flush (default 5000, AC #3).
    """

    def __init__(
        self,
        cache: CacheProtocol,
        db: DatabaseProtocol,
        *,
        flush_interval: float = 2.0,
        flush_dirty_threshold: int = 5000,
    ) -> None:
        self._cache: CacheProtocol = cache
        self._db: DatabaseProtocol = db
        self._flush_interval: float = flush_interval
        self._flush_dirty_threshold: int = flush_dirty_threshold

        # Warm-up indices (built by load_balances_from_postgres)
        self._subscriber_to_msisdn: dict[str, str] = {}
        self._msisdn_to_subscriber: dict[str, str] = {}

        # In-process dirty set and ledger queue (shared between hot path and flusher)
        self._dirty_msisdns: set[str] = set()
        self._ledger_queue: list[LedgerRow] = []

        # Flusher loop control
        self._flusher_running: bool = False
        self._flusher_task: asyncio.Task[None] | None = None

    async def warmup(self) -> None:
        """Run Postgres → Valkey warm-up and build indices (Task 3, AC #5).

        Calls ``startup.load_balances_from_postgres`` which queries all balances,
        seeds ``balance:{msisdn}`` keys, and returns the subscriber→msisdn index.
        Stores the indices for hot-path msisdn resolution. Must complete before
        the consumer loop starts.
        """
        state = await load_balances_from_postgres(self._db, self._cache)
        self._subscriber_to_msisdn = dict(state.subscriber_to_msisdn)
        self._msisdn_to_subscriber = dict(state.msisdn_to_subscriber)

    async def deduct(self, cdr: CdrEvent) -> None:
        """Hot-path balance deduction (BalanceHook called by BatchProcessor).

        Resolves msisdn from the CDR's subscriber_id, atomically ``INCRBY
        balance:{msisdn} -cost_paise``, marks msisdn dirty, and enqueues a ledger
        row. Emits an OTEL span. Operates in O(1) with no blocking I/O.

        Idempotency: the caller (Story 2.2 BatchProcessor) guarantees this is
        invoked only on first-sight events; this engine does NOT add a dedup guard.

        Parameters
        ----------
        cdr : CdrEvent
            Validated CDR payload (voice/sms/data). Carries ``subscriber_id``,
            ``cdr_id``, ``cost_paise``, ``cdr_type``, and for voice: ``duration_seconds``.
        """
        sub_id_str = str(cdr.subscriber_id)
        msisdn = self._subscriber_to_msisdn.get(sub_id_str)

        if msisdn is None:
            # Subscriber not in warm-up index (new subscriber, no wallet row).
            # Log warning (PII-safe: subscriber_id only) and skip deduction.
            # The CDR still forwards to enriched — this is a degradation, not a crash.
            logger.warning(
                "deduct: subscriber_id=%s not in warm-up index (no msisdn), skipping deduction",
                sub_id_str,
            )
            return

        cost_paise = cdr.cost_paise  # honour incoming (producer pre-rated)
        cdr_id_str = str(cdr.cdr_id)

        with tracer.start_as_current_span("balance.deduction") as span:
            span.set_attribute("cdr.cdr_type", cdr.cdr_type)
            span.set_attribute("cdr.cost_paise", cost_paise)

            # Atomic INCRBY balance:{msisdn} -cost_paise
            # Returns the NEW balance (after deduction); before = after + cost.
            key = f"balance:{msisdn}"
            balance_after = await self._cache.incr_by(key, -cost_paise)
            balance_before = balance_after + cost_paise

            span.set_attribute("balance.balance_after", balance_after)
            span.set_attribute("balance.msisdn_last4", msisdn[-4:])  # PII-safe

            # Mark msisdn dirty for flusher
            self._dirty_msisdns.add(msisdn)

            # Enqueue ledger row (flush-adjacent async path)
            self._ledger_queue.append(
                LedgerRow(
                    subscriber_id=sub_id_str,
                    amount_paise=-cost_paise,
                    cdr_id=cdr_id_str,
                    description=cdr.cdr_type,
                    balance_before=balance_before,
                    balance_after=balance_after,
                )
            )

            logger.debug(
                "deduct: cdr_id=%s, msisdn[-4:]=%s, cost=%d, balance_before=%d, balance_after=%d",
                cdr_id_str,
                msisdn[-4:],
                cost_paise,
                balance_before,
                balance_after,
            )

    async def _flush(self) -> None:
        """Flush dirty balances to Postgres and insert ledger rows (Task 4, AC #3).

        Reads current ``balance:{msisdn}`` for all dirty msisdns, bulk-upserts
        ``billing_wallet_balances`` (ON CONFLICT DO UPDATE), batch-inserts the
        queued ledger rows, and clears the dirty set + queue. Keys are NOT
        deleted (they remain the live buffer).
        """
        if not self._dirty_msisdns:
            return

        dirty = list(self._dirty_msisdns)
        self._dirty_msisdns.clear()

        ledger_rows = list(self._ledger_queue)
        self._ledger_queue.clear()

        # Read current balances from Valkey for dirty msisdns
        balance_reads: dict[str, int] = {}
        for msisdn in dirty:
            key = f"balance:{msisdn}"
            val_str = await self._cache.get_str(key)
            if val_str is not None:
                balance_reads[msisdn] = int(val_str)
            else:
                logger.warning("flush: balance key missing for msisdn[-4:]=%s", msisdn[-4:])

        # Upsert billing_wallet_balances + insert ledger rows via one transaction
        async with self._db.transaction() as conn:
            for msisdn, balance_paise in balance_reads.items():
                subscriber_id = self._msisdn_to_subscriber.get(msisdn)
                if subscriber_id is None:
                    logger.warning("flush: subscriber_id missing for msisdn[-4:]=%s", msisdn[-4:])
                    continue
                await conn.execute(_BALLED_UPSERT_SQL, (subscriber_id, msisdn, balance_paise))

            for row in ledger_rows:
                await conn.execute(
                    _LEDGER_INSERT_SQL,
                    (
                        row.subscriber_id,
                        row.amount_paise,
                        row.cdr_id,
                        row.description,
                        row.balance_before,
                        row.balance_after,
                    ),
                )

        logger.info(
            "flush: upserted %d wallets, inserted %d ledger rows",
            len(balance_reads),
            len(ledger_rows),
        )

    async def _flusher_loop(self) -> None:
        """Background flusher loop: triggers on 2s or 5000 dirty keys (Task 4).

        Exits when ``_flusher_running`` is cleared (checked each inner tick) so
        ``stop`` can shut it down deterministically without cancelling the task.
        """
        self._flusher_running = True
        loop = asyncio.get_running_loop()

        while self._flusher_running:
            try:
                # Wait for interval OR dirty threshold, whichever comes first.
                deadline = loop.time() + self._flush_interval
                while loop.time() < deadline and self._flusher_running:
                    if len(self._dirty_msisdns) >= self._flush_dirty_threshold:
                        break
                    await asyncio.sleep(0.1)

                if self._flusher_running:
                    await self._flush()
            except Exception:
                logger.exception("flusher: exception in flush loop")
                await asyncio.sleep(1)  # back off on error

    async def run(self) -> None:
        """Start the flusher background task (call after warmup)."""
        if self._flusher_task is not None:
            logger.warning("run: flusher already running")
            return

        self._flusher_task = asyncio.create_task(self._flusher_loop())
        logger.info(
            "flusher: started (interval=%s, threshold=%s)",
            self._flush_interval,
            self._flush_dirty_threshold,
        )

    async def stop(self) -> None:
        """Stop the flusher loop and flush once more (graceful shutdown).

        Clears ``_flusher_running`` so the loop exits on its next tick (no
        cancellation needed), awaits its completion with a timeout backstop,
        then performs a final drain flush.
        """
        self._flusher_running = False

        if self._flusher_task is not None:
            try:
                await asyncio.wait_for(self._flusher_task, timeout=5)
            except TimeoutError:
                logger.warning("stop: flusher did not exit within 5s, cancelling")
                self._flusher_task.cancel()
            except Exception:
                logger.exception("stop: exception waiting for flusher exit")
            self._flusher_task = None

        # Final flush to drain any dirty keys / ledger rows that landed after the
        # loop stopped (the loop skips its own final flush once _flusher_running
        # is False).
        try:
            await self._flush()
        except Exception:
            logger.exception("stop: exception during final flush")

        logger.info("flusher: stopped")


__all__ = ["BalanceEngine", "LedgerRow"]
