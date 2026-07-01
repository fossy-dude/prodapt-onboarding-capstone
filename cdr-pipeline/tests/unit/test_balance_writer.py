"""Unit tests for balance writer (Story 2.3, Task 7)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID

import pytest

from consumer.balance_writer import BalanceEngine, LedgerRow
from models.cdr import SmsCdr

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeCursor:
    """Mimics a psycopg cursor: async context manager with execute/executemany/fetch."""

    def __init__(self, rows: list[tuple], executed: list[tuple]) -> None:
        self._rows = rows
        self._executed = executed

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, sql: str, *params: object) -> FakeCursor:
        self._executed.append((sql, params))
        return self

    async def executemany(self, sql: str, params_seq: object) -> None:
        # psycopg3 executemany shape: an iterable of param tuples. Recorded as a
        # list so tests can assert on the flushed batch.
        self._executed.append((sql, list(params_seq)))  # type: ignore[arg-type]

    async def fetchall(self) -> list[tuple]:
        return self._rows

    async def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, fetch_rows: list[tuple], executed: list[tuple]) -> None:
        self._fetch_rows = fetch_rows
        self._executed = executed

    def cursor(self) -> FakeCursor:
        # psycopg3 cursors are async context managers; _flush uses
        # ``async with conn.cursor() as cur: await cur.executemany(...)``.
        return FakeCursor(self._fetch_rows, self._executed)

    async def execute(self, sql: str, *params: object) -> FakeCursor:
        self._executed.append((sql, params))
        return FakeCursor(self._fetch_rows, self._executed)


class FakeDB:
    def __init__(self, fetch_rows: list[tuple] | None = None) -> None:
        self._fetch_rows = fetch_rows or []
        self.executed: list[tuple] = []  # (sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeConn]:
        yield FakeConn(self._fetch_rows, self.executed)

    async def ping(self) -> bool:
        return True


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.incr_by_calls: list[tuple[str, int]] = []
        self.set_many_calls: list[dict[str, int]] = []
        self.deleted: list[str] = []

    async def ping(self) -> bool:
        return True

    async def set_str(self, key: str, value: str, ex: int) -> None:
        self.store[key] = value

    async def get_str(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.store.pop(key, None)

    async def set_nx(self, key: str, value: str, ex: int) -> bool:
        if key in self.store:
            return False
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        v = int(self.store.get(key, "0")) + 1
        self.store[key] = str(v)
        return v

    async def incr_by(self, key: str, amount: int) -> int:
        self.incr_by_calls.append((key, amount))
        v = int(self.store.get(key, "0")) + amount
        self.store[key] = str(v)
        return v

    async def set_many(self, mapping: dict[str, int]) -> None:
        self.set_many_calls.append(dict(mapping))
        for k, v in mapping.items():
            self.store[k] = str(v)


_SUB = "0192a4d0-1234-7000-8000-000000000abc"
_MSISDN = "9876543210"


def _sms(cost: int, cdr_id: str = "0192a4d0-0001-7000-8000-000000000001", sub: str = _SUB) -> SmsCdr:
    return SmsCdr(
        cdr_id=UUID(cdr_id),
        session_id=UUID("0192a4d0-abcd-7000-8000-000000000001"),
        subscriber_id=UUID(sub),
        telecom_circle="KA",
        cost_paise=cost,
        start_time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        message_direction="MT",
        sms_status="delivered",
    )


def _engine(
    *, flush_interval: float = 2.0, flush_dirty_threshold: int = 5000
) -> tuple[BalanceEngine, FakeCache, FakeDB]:
    """Build an engine with warm-up indices seeded for one subscriber/msisdn."""
    cache = FakeCache()
    db = FakeDB()
    engine = BalanceEngine(cache, db, flush_interval=flush_interval, flush_dirty_threshold=flush_dirty_threshold)
    engine._subscriber_to_msisdn = {_SUB: _MSISDN}
    engine._msisdn_to_subscriber = {_MSISDN: _SUB}
    return engine, cache, db


def test_deduct_issues_incrby_and_marks_dirty():
    """Deduct issues INCRBY balance:{msisdn} -cost, marks dirty, enqueues ledger."""
    engine, cache, _ = _engine()
    cache.store["balance:9876543210"] = "10000"

    asyncio.run(engine.deduct(_sms(cost=250)))

    assert cache.incr_by_calls == [("balance:9876543210", -250)]
    assert _MSISDN in engine._dirty_msisdns
    assert len(engine._ledger_queue) == 1
    row = engine._ledger_queue[0]
    assert row.subscriber_id == _SUB
    assert row.amount_paise == -250
    assert row.balance_before == 10000  # 9750 + 250
    assert row.balance_after == 9750
    assert cache.store["balance:9876543210"] == "9750"


def test_deduct_zero_cost_unlimited_still_logged():
    """Zero-charge deduction still enqueues a ledger row (AC #7 unlimited bundle)."""
    engine, cache, _ = _engine()
    cache.store["balance:9876543210"] = "10000"

    asyncio.run(engine.deduct(_sms(cost=0)))

    assert cache.incr_by_calls == [("balance:9876543210", 0)]
    assert len(engine._ledger_queue) == 1
    row = engine._ledger_queue[0]
    assert row.amount_paise == 0
    assert row.balance_before == 10000
    assert row.balance_after == 10000


def test_deduct_unknown_subscriber_skips_when_not_in_db():
    """Subscriber absent from index and DB → skip deduction (no INCRBY)."""
    engine, cache, _ = _engine()  # FakeDB has no rows → fetchone returns None

    asyncio.run(engine.deduct(_sms(cost=250, sub="0192a4d0-9999-7000-8000-000000000def")))

    assert cache.incr_by_calls == []
    assert len(engine._dirty_msisdns) == 0
    assert len(engine._ledger_queue) == 0


def test_deduct_falls_back_to_db_for_new_subscriber():
    """Subscriber absent from warm-up index but present in DB → deduction proceeds."""
    new_sub = "0192a4d0-9999-7000-8000-000000000def"
    new_msisdn = "9999999999"
    cache = FakeCache()
    db = FakeDB(fetch_rows=[(new_msisdn, 5000)])
    engine = BalanceEngine(cache, db)
    engine._subscriber_to_msisdn = {_SUB: _MSISDN}
    engine._msisdn_to_subscriber = {_MSISDN: _SUB}
    cache.store[f"balance:{_MSISDN}"] = "10000"

    asyncio.run(engine.deduct(_sms(cost=250, sub=new_sub)))

    assert cache.incr_by_calls == [(f"balance:{new_msisdn}", -250)]
    assert new_msisdn in engine._dirty_msisdns
    assert len(engine._ledger_queue) == 1
    assert engine._ledger_queue[0].subscriber_id == new_sub
    assert engine._ledger_queue[0].amount_paise == -250
    assert engine._subscriber_to_msisdn[new_sub] == new_msisdn
    assert engine._msisdn_to_subscriber[new_msisdn] == new_sub
    assert cache.store[f"balance:{new_msisdn}"] == str(5000 - 250)


def test_deduct_db_fallback_skips_cache_seed_if_key_exists():
    """DB fallback does not overwrite an already-live balance key in Valkey."""
    new_sub = "0192a4d0-9999-7000-8000-000000000def"
    new_msisdn = "9999999999"
    cache = FakeCache()
    db = FakeDB(fetch_rows=[(new_msisdn, 5000)])
    engine = BalanceEngine(cache, db)
    engine._subscriber_to_msisdn = {}
    engine._msisdn_to_subscriber = {}
    # Key already exists in cache with a live (different) value
    cache.store[f"balance:{new_msisdn}"] = "4000"

    asyncio.run(engine.deduct(_sms(cost=100, sub=new_sub)))

    # INCRBY applied to the existing live value, not reset to DB snapshot
    assert cache.incr_by_calls == [(f"balance:{new_msisdn}", -100)]
    assert cache.store[f"balance:{new_msisdn}"] == "3900"
    # set_many was NOT called (key already existed)
    assert cache.set_many_calls == []


def test_flush_upsert_uses_on_conflict_and_keeps_key():
    """Flusher upserts with ON CONFLICT (msisdn) and does NOT delete the key."""
    engine, cache, db = _engine()
    cache.store["balance:9876543210"] = "9750"
    engine._dirty_msisdns.add(_MSISDN)

    asyncio.run(engine._flush())

    # The upsert SQL carries the ON CONFLICT clause
    assert any("ON CONFLICT (msisdn)" in sql for sql, _ in db.executed)
    # Dirty set cleared
    assert _MSISDN not in engine._dirty_msisdns
    # Key NOT deleted — still the live buffer
    assert cache.store.get("balance:9876543210") == "9750"
    assert cache.deleted == []


def test_flush_inserts_queued_ledger_rows():
    """Flusher batch-inserts queued ledger rows with before/after balances."""
    engine, cache, db = _engine()
    cache.store["balance:9876543210"] = "9750"
    engine._dirty_msisdns.add(_MSISDN)
    engine._ledger_queue.append(LedgerRow(_SUB, -250, "0192a4d0-0001-7000-8000-000000000001", "sms", 10000, 9750))

    asyncio.run(engine._flush())

    # One executemany (wallet upsert) + one executemany (ledger insert)
    assert len(db.executed) == 2
    ledger_sql = db.executed[1][0]
    assert "billing_transactions" in ledger_sql
    # executemany records the batch (list of param tuples); assert the first row.
    ledger_rows = db.executed[1][1]
    assert ledger_rows[0][0] == _SUB  # subscriber_id
    assert ledger_rows[0][1] == -250  # amount_paise
    assert ledger_rows[0][4] == 10000  # balance_before
    assert ledger_rows[0][5] == 9750  # balance_after


def test_flusher_triggers_on_dirty_threshold():
    """Flusher flushes immediately when dirty count reaches the threshold mid-loop (AC #3)."""
    engine, cache, db = _engine(flush_interval=10.0, flush_dirty_threshold=1)
    cache.store["balance:9876543210"] = "9750"

    async def run():
        task = asyncio.create_task(engine._flusher_loop())
        # Let the loop enter its wait, THEN cross the threshold so the 0.3s flush
        # is provably triggered by the threshold — not pre-satisfied at t=0.
        await asyncio.sleep(0.05)
        engine._dirty_msisdns.add(_MSISDN)
        await asyncio.sleep(0.3)  # far below the 10s interval
        engine._flusher_running = False
        await task

    asyncio.run(run())

    # Flush happened quickly → proves the threshold (not the 10s timer) fired
    assert len(db.executed) >= 1


def test_flusher_triggers_on_interval():
    """Flusher flushes on the timed interval when below the dirty threshold (AC #3)."""
    engine, cache, db = _engine(flush_interval=0.1, flush_dirty_threshold=9999)
    cache.store["balance:9876543210"] = "9750"
    engine._dirty_msisdns.add(_MSISDN)  # 1 dirty, below threshold → waits for timer

    async def run():
        task = asyncio.create_task(engine._flusher_loop())
        await asyncio.sleep(0.5)  # well past the 0.1s interval
        engine._flusher_running = False
        await task

    asyncio.run(run())

    # Flush happened on the timer (threshold never reached)
    assert len(db.executed) >= 1


def test_stop_drains_dirty_set():
    """stop() performs a final flush draining any remaining dirty keys."""
    engine, cache, db = _engine()
    cache.store["balance:9876543210"] = "9750"
    engine._dirty_msisdns.add(_MSISDN)

    asyncio.run(engine.stop())

    assert _MSISDN not in engine._dirty_msisdns
    assert any("ON CONFLICT (msisdn)" in sql for sql, _ in db.executed)


def test_deduct_overdraft_allows_negative_and_signals():
    """Overdraft policy = allow + signal: balance goes negative, no refund/clamp.

    The OTEL span attribute + counter are emitted but are no-ops without a
    MeterProvider/exporter (Story 1.5 infra); this test locks the *allow* half of
    the policy — the balance and ledger row persist the negative value.
    """
    engine, cache, _ = _engine()
    cache.store["balance:9876543210"] = "100"  # tiny balance

    asyncio.run(engine.deduct(_sms(cost=250)))  # 100 - 250 = -150 (overdraft)

    # Balance went negative — NOT clamped to 0 or refunded.
    assert cache.store["balance:9876543210"] == "-150"
    assert cache.incr_by_calls == [("balance:9876543210", -250)]
    row = engine._ledger_queue[0]
    assert row.balance_before == 100
    assert row.balance_after == -150
    assert row.amount_paise == -250


def test_deduct_blocks_at_ledger_cap_until_flush():
    """Over-cap ledger queue blocks deduct until a successful flush frees capacity."""
    engine, cache, _ = _engine()
    engine._ledger_cap = 2  # tiny cap for the test
    cache.store["balance:9876543210"] = "10000"
    # Pre-fill the ledger to the cap and close the gate (simulate a cap hit).
    engine._ledger_queue.append(LedgerRow(_SUB, -1, "x", "sms", 0, 0))
    engine._ledger_queue.append(LedgerRow(_SUB, -1, "y", "sms", 0, 0))
    engine._drained.clear()

    async def run():
        task = asyncio.create_task(engine.deduct(_sms(cost=250)))
        await asyncio.sleep(0.05)
        # deduct is blocked on the drained gate (queue at cap).
        assert not task.done()
        # A successful flush drains the queue and re-opens the gate.
        await engine._flush()
        await asyncio.wait_for(task, timeout=1.0)
        assert task.done()

    asyncio.run(run())

    # The blocked deduction landed after the flush (queue was drained to 0, then
    # this row appended); it's below the cap so the gate stays open.
    assert len(engine._ledger_queue) == 1
    assert engine._ledger_queue[0].amount_paise == -250
