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

Overdraft policy (resolved in code review 2026-06-23): **allow + signal**. The
hot path never refunds or clamps — ``INCRBY`` is the single atomic step and stays
O(1). When ``balance_after < 0`` the deduction still lands (prepaid credit /
reconcile-out-of-band model), but a ``balance.overdraft`` span attribute and a
counter are emitted so operators can see it. Blocking/clamping would require an
atomic Lua script to avoid a race on the P95 path — out of scope for this story.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace

from consumer.startup import load_balances_from_postgres

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol
    from consumer.notification_trigger import NotificationTrigger
    from models.cdr import CdrEvent

logger = logging.getLogger("consumer.balance_writer")

tracer = trace.get_tracer(__name__)
_meter = metrics.get_meter(__name__)

# Counters are no-ops until an exporter/MeterProvider is wired (Story 1.5 infra);
# like the deduction span, emitting them now makes the behaviour observable later.
_overdraft_counter = _meter.create_counter(
    "balance.overdraft.count",
    unit="1",
    description="Deductions that drove the wallet balance below zero (overdraft; allow+signal policy).",
)
_backpressure_counter = _meter.create_counter(
    "balance.backpressure.count",
    unit="1",
    description="Deductions delayed because the dirty/ledger buffer reached its cap (sustained flush failure).",
)
_flush_failure_counter = _meter.create_counter(
    "balance.flush.failure.count",
    unit="1",
    description="Flush attempts that raised — rows are retried (loop) or at risk of loss (shutdown).",
)

# Backpressure caps: 20x the default dirty threshold. Under sustained DB failure the
# flusher cannot drain, so these bound memory. When crossed, ``deduct`` blocks on an
# Event until a successful flush frees capacity — that backpressure flows up to the
# consumer (it stops polling), which is preferable to OOM.
_LEDGER_CAP = 100_000
_DIRTY_CAP = 100_000

# Bulk upsert: ON CONFLICT (msisdn) keeps the wallet row in sync with the live
# Valkey buffer. subscriber_id is supplied so a genuinely new msisdn inserts too.
# psycopg3's default cursor uses ``%s`` pyformat placeholders (NOT ``$N``).
_BALANCE_UPSERT_SQL = """\
INSERT INTO billing_wallet_balances (
    id, subscriber_id, msisdn, balance_paise, last_deduction_at, created_at, modified_at
) VALUES (
    gen_random_uuid(),
    %s,
    %s,
    %s,
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
    %s,
    'cdr_deduction',
    %s,
    'cdr',
    %s,
    %s,
    %s,
    %s,
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
        notification_trigger: "NotificationTrigger | None" = None,
    ) -> None:
        self._cache: CacheProtocol = cache
        self._db: DatabaseProtocol = db
        self._flush_interval: float = flush_interval
        self._flush_dirty_threshold: int = flush_dirty_threshold
        self._notification_trigger = notification_trigger

        # Warm-up indices (built by load_balances_from_postgres)
        self._subscriber_to_msisdn: dict[str, str] = {}
        self._msisdn_to_subscriber: dict[str, str] = {}
        self._warmup_count: int = 0

        # In-process dirty set and ledger queue (shared between hot path and flusher)
        self._dirty_msisdns: set[str] = set()
        self._ledger_queue: list[LedgerRow] = []

        # Flusher loop control
        self._flusher_running: bool = False
        self._flusher_task: asyncio.Task[None] | None = None

        # Serialise _flush across the flusher loop and stop()'s final drain so the
        # two can never overlap (esp. on the 5s-timeout cancel path).
        self._flush_lock: asyncio.Lock = asyncio.Lock()

        # Backpressure gate: set when there is buffer capacity. ``deduct`` awaits it
        # before doing work, so once a cap is hit the consumer pauses until a flush
        # succeeds (which re-sets it). Starts set (capacity available).
        self._drained: asyncio.Event = asyncio.Event()
        self._drained.set()

        self._ledger_cap: int = _LEDGER_CAP
        self._dirty_cap: int = _DIRTY_CAP

    @property
    def warmup_count(self) -> int:
        """Number of balance keys seeded by the last warm-up (0 before warm-up)."""
        return self._warmup_count

    def set_notification_trigger(self, trigger: NotificationTrigger) -> None:
        """Inject notification trigger after engine construction (Story 4.1).

        Parameters
        ----------
        trigger : NotificationTrigger
            Notification trigger instance to inject.
        """
        self._notification_trigger = trigger

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
        self._warmup_count = state.count

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
        # Backpressure: if the flusher is behind and the buffer is at capacity,
        # wait here rather than letting the dirty set / ledger queue grow unbounded.
        # This blocks the consumer's record processing, which is the intended
        # backpressure signal (better than OOM under sustained DB failure).
        await self._drained.wait()

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

            # Notification trigger: publish LOW_BALANCE or BALANCE_DEPLETED events
            # Must use asyncio.create_task to keep hot path O(1) — no await.
            if self._notification_trigger is not None:
                # Extract trace_id from current OTEL span (32 hex chars)
                span_context = span.get_span_context()
                span_trace_id = format(span_context.trace_id, "032x")

                # Fire-and-forget notification check (task exceptions logged by callback)
                task = asyncio.create_task(
                    self._notification_trigger.check_and_publish(
                        msisdn=msisdn,
                        subscriber_id=sub_id_str,
                        balance_after=balance_after,
                        trace_id=span_trace_id,
                    )
                )
                # Surface task exceptions without blocking the hot path
                task.add_done_callback(
                    lambda t: t.exception() and logger.error("notification_trigger failed: %s", t.exception())
                )

            # Overdraft signal (allow + signal policy): the deduction is NOT undone,
            # but a negative result is made visible so it can be reconciled.
            if balance_after < 0:
                span.set_attribute("balance.overdraft", True)
                _overdraft_counter.add(1, {"cdr.cdr_type": cdr.cdr_type})

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

            # If this deduction pushed the buffer to its cap, close the gate so the
            # next ``deduct`` blocks until a flush frees capacity.
            if len(self._ledger_queue) >= self._ledger_cap or len(self._dirty_msisdns) >= self._dirty_cap:
                self._drained.clear()
                _backpressure_counter.add(1, {"buffer": "cap"})

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

        Snapshots the current dirty set + ledger queue, reads current
        ``balance:{msisdn}`` for the dirty msisdns, bulk-upserts
        ``billing_wallet_balances`` (ON CONFLICT DO UPDATE) and batch-inserts the
        queued ledger rows inside one transaction, then — only on a successful
        commit — drops the flushed items. On failure nothing is cleared, so the
        next flush retries the same rows (the upsert is idempotent and the
        transaction rolled back, so no double-count). Keys are NOT deleted.

        Serialised by ``_flush_lock`` so the flusher loop and ``stop()``'s final
        drain never overlap.
        """
        async with self._flush_lock:
            if not self._dirty_msisdns and not self._ledger_queue:
                return

            dirty_snapshot = list(self._dirty_msisdns)
            ledger_snapshot = list(self._ledger_queue)

            upsert_params: list[tuple[str, str, int]] = []
            missing_subscriber: list[str] = []
            for msisdn in dirty_snapshot:
                subscriber_id = self._msisdn_to_subscriber.get(msisdn)
                if subscriber_id is None:
                    # Reverse-index miss (shouldn't happen — both indices are built
                    # together). Defer this wallet: it's re-marked dirty below so
                    # the next flush retries it rather than being silently dropped.
                    missing_subscriber.append(msisdn)
                    logger.warning("flush: subscriber_id missing for msisdn[-4:]=%s; deferring", msisdn[-4:])
                    continue
                val_str = await self._cache.get_str(f"balance:{msisdn}")
                if val_str is None:
                    logger.warning("flush: balance key missing for msisdn[-4:]=%s", msisdn[-4:])
                    continue
                upsert_params.append((subscriber_id, msisdn, int(val_str)))

            ledger_params = [
                (
                    row.subscriber_id,
                    row.amount_paise,
                    row.cdr_id,
                    row.description,
                    row.balance_before,
                    row.balance_after,
                )
                for row in ledger_snapshot
            ]

            # One round-trip per statement (executemany), not one per row.
            # psycopg3's executemany lives on the cursor, not the connection.
            async with self._db.transaction() as conn:
                if upsert_params:
                    async with conn.cursor() as cur:
                        await cur.executemany(_BALANCE_UPSERT_SQL, upsert_params)
                if ledger_params:
                    async with conn.cursor() as cur:
                        await cur.executemany(_LEDGER_INSERT_SQL, ledger_params)

            # Commit succeeded — clear ONLY the flushed items. Anything appended by
            # a concurrent deduct during the awaits above is preserved (set
            # difference for dirty; drop-the-flushed-prefix for the ledger queue).
            # NB: a msisdn deducted again mid-flush is removed from the dirty set
            # by difference_update and self-heals on its next deduct — same
            # granularity as the prior implementation, but no longer lost on failure.
            self._dirty_msisdns.difference_update(dirty_snapshot)
            del self._ledger_queue[: len(ledger_snapshot)]
            # Re-mark deferred wallets so the next flush retries them.
            self._dirty_msisdns.update(missing_subscriber)
            # A successful flush made room — release backpressure.
            self._drained.set()

            logger.info(
                "flush: upserted %d wallets, inserted %d ledger rows",
                len(upsert_params),
                len(ledger_params),
            )

    async def _flusher_loop(self) -> None:
        """Background flusher loop: triggers on 2s or 5000 dirty keys (Task 4).

        Exits when ``_flusher_running`` is cleared (checked each inner tick) so
        ``stop`` can shut it down deterministically without cancelling the task.
        ``_flusher_running`` is also set here so direct callers (tests) work even
        without going through ``run``.
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
                _flush_failure_counter.add(1, {"phase": "loop"})
                logger.exception("flusher: exception in flush loop")
                await asyncio.sleep(1)  # back off on error; rows remain for retry

    async def run(self) -> None:
        """Start the flusher background task (call after warmup)."""
        if self._flusher_task is not None:
            logger.warning("run: flusher already running")
            return

        # Set the flag BEFORE create_task so an immediate stop() (before the loop
        # has been scheduled) still observes _flusher_running=True and shuts down
        # cleanly instead of leaving a stray cycle.
        self._flusher_running = True
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
        then performs a final drain flush. A failure of that final flush is
        surfaced at CRITICAL (+ counter) rather than swallowed, because it means
        dirty balances / ledger rows were NOT persisted at shutdown.
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
        # is False). A failure here is shutdown-time data loss — make it loud.
        try:
            await self._flush()
        except Exception:
            _flush_failure_counter.add(1, {"phase": "shutdown"})
            logger.critical(
                "stop: final flush FAILED — dirty/ledger NOT drained; operator must "
                "reconcile billing_wallet_balances/billing_transactions against Valkey",
                exc_info=True,
            )

        logger.info("flusher: stopped")


__all__ = ["BalanceEngine", "LedgerRow"]
