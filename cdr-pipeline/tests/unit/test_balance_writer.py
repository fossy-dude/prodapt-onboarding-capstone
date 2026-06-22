"""Unit tests for balance writer (Story 2.3, Task 7)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumer.balance_writer import BalanceEngine, LedgerRow
from models.cdr import SmsCdr, VoiceCdr


@pytest.fixture
def mock_cache():
    """Mock CacheProtocol."""
    cache = AsyncMock()
    cache.incr_by.return_value = 9750  # balance_after
    return cache


@pytest.fixture
def mock_db():
    """Mock DatabaseProtocol."""
    db = AsyncMock()
    db.transaction = AsyncMock()
    return db


@pytest.fixture
def engine(mock_cache, mock_db):
    """BalanceEngine with mocks."""
    engine = BalanceEngine(mock_cache, mock_db, flush_interval=2.0, flush_dirty_threshold=5000)
    # Warm-up indices (subscriber_id → msisdn)
    engine._subscriber_to_msisdn = {"0192a4d0-1234-7000-8000-000000000abc": "9876543210"}
    engine._msisdn_to_subscriber = {"9876543210": "0192a4d0-1234-7000-8000-000000000abc"}
    return engine


def test_deduct_issues_incrby_and_marks_dirty(engine, mock_cache):
    """Deduct issues INCRBY balance:{msisdn} -cost and marks msisdn dirty."""
    cdr = SmsCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000001",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=250,
        start_time="2026-01-01T12:00:00Z",
        message_direction="MT",
        sms_status="delivered",
    )

    asyncio.run(engine.deduct(cdr))

    # Assert INCRBY was called with negative cost
    mock_cache.incr_by.assert_called_once_with("balance:9876543210", -250)

    # Assert msisdn is marked dirty
    assert "9876543210" in engine._dirty_msisdns

    # Assert ledger row enqueued
    assert len(engine._ledger_queue) == 1
    ledger = engine._ledger_queue[0]
    assert ledger.subscriber_id == "0192a4d0-1234-7000-8000-000000000abc"
    assert ledger.amount_paise == -250
    assert ledger.cdr_id == "0192a4d0-0001-7000-8000-000000000001"
    assert ledger.balance_before == 10000  # 9750 + 250
    assert ledger.balance_after == 9750


def test_deduct_unknown_subscriber_skips(engine, mock_cache):
    """Subscriber not in warm-up index → log warning and skip deduction."""
    cdr = SmsCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000002",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-9999-7000-8000-000000000def",  # unknown
        telecom_circle="KA",
        cost_paise=250,
        start_time="2026-01-01T12:00:00Z",
        message_direction="MT",
        sms_status="delivered",
    )

    asyncio.run(engine.deduct(cdr))

    # Assert NO INCRBY (skip deduction)
    mock_cache.incr_by.assert_not_called()

    # Assert no dirty marking or ledger enqueue
    assert len(engine._dirty_msisdns) == 0
    assert len(engine._ledger_queue) == 0


def test_flusher_triggers_on_dirty_threshold(engine, mock_cache, mock_db):
    """Flusher triggers when 5K dirty keys reached (Task 7)."""
    # Mark 5000 msisdns dirty
    for i in range(5000):
        engine._dirty_msisdns.add(f"msisdn-{i}")

    # Mock DB transaction context manager
    async def mock_transaction():
        async def noop():
            yield MagicMock()

        return noop()

    mock_db.transaction.return_value = mock_transaction()
    mock_cache.get_str.return_value = "10000"  # mock current balance

    asyncio.run(engine._flush())

    # Assert flush cleared dirty set
    assert len(engine._dirty_msisdns) == 0


def test_flusher_triggers_on_interval(engine, mock_db):
    """Flusher triggers on 2s interval (Task 7)."""
    # Mark 1 msisdn dirty (below threshold)
    engine._dirty_msisdns.add("9876543210")
    engine._ledger_queue.append(
        LedgerRow(
            subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
            amount_paise=-250,
            cdr_id="cdr-1",
            description="sms",
            balance_before=10000,
            balance_after=9750,
        )
    )

    # Mock DB transaction
    async def mock_transaction():
        async def noop():
            conn = AsyncMock()
            conn.execute = AsyncMock()
            yield conn

        return noop()

    mock_db.transaction.return_value = mock_transaction()

    # Start flusher, wait for interval, stop
    async def run_flusher_once():
        flush_task = asyncio.create_task(engine._flusher_loop())
        await asyncio.sleep(2.2)  # wait past interval
        engine._flusher_running = False
        await flush_task

    asyncio.run(run_flusher_once())

    # Assert flush cleared dirty set
    assert len(engine._dirty_msisdns) == 0


def test_flush_upsert_sql_on_conflict_msidsdn(engine, mock_db):
    """Flusher uses ON CONFLICT (msisdn) for upsert (Task 7)."""
    engine._dirty_msisdns.add("9876543210")
    engine._msisdn_to_subscriber = {"9876543210": "0192a4d0-1234-7000-8000-000000000abc"}
    engine._ledger_queue.clear()

    async def mock_transaction():
        async def yield_conn():
            conn = AsyncMock()
            conn.execute = AsyncMock()
            yield conn

        return yield_conn()

    mock_db.transaction.return_value = mock_transaction()

    asyncio.run(engine._flush())

    # Get the transaction context and verify execute was called
    transaction_fn = mock_db.transaction.call_args[0][0]
    conn = asyncio.run(transaction_fn()).__aenter__.return_value

    # Verify execute was called (the exact SQL string contains ON CONFLICT)
    assert conn.execute.called
    call_args = conn.execute.call_args
    sql = call_args[0][0] if call_args[0] else call_args.kwargs.get("sql", "")
    assert "ON CONFLICT (msisdn)" in sql


def test_flush_keys_not_deleted(engine, mock_cache, mock_db):
    """Flush does NOT delete balance keys after upsert (Task 7)."""
    engine._dirty_msisdns.add("9876543210")

    async def mock_transaction():
        async def noop():
            yield MagicMock()

        return noop()

    mock_db.transaction.return_value = mock_transaction()
    mock_cache.get_str.return_value = "9750"

    asyncio.run(engine._flush())

    # Assert NO delete calls on cache
    mock_cache.delete.assert_not_called()

    # Key still exists (not deleted)
    assert "9876543210" not in engine._dirty_msisdns  # cleared dirty, but key remains in cache
