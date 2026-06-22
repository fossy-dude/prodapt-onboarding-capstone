"""Unit tests for startup warm-up (Story 2.3, Task 7)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from consumer.startup import BalanceWarmupState, load_balances_from_postgres


@pytest.fixture
def mock_db():
    """Mock DatabaseProtocol with transaction returning a cursor."""
    db = AsyncMock()

    # Mock transaction context manager
    async def mock_transaction():
        async def yield_conn():
            conn = AsyncMock()
            # Mock cursor from execute
            cur = AsyncMock()
            cur.fetchall.return_value = [
                (
                    "0192a4d0-1234-7000-8000-000000000abc",
                    "9876543210",
                    100000,
                ),
                (
                    "0192a4d0-9999-7000-8000-000000000def",
                    "9876543211",
                    50000,
                ),
            ]
            conn.execute.return_value = cur
            yield conn

        return yield_conn()

    db.transaction = mock_transaction
    return db


@pytest.fixture
def mock_cache():
    """Mock CacheProtocol with set_many."""
    cache = AsyncMock()
    return cache


def test_load_balances_queries_billing_wallet_balances(mock_db, mock_cache):
    """Warm-up queries billing_wallet_balances (Task 7)."""
    asyncio.run(load_balances_from_postgres(mock_db, mock_cache))

    # Assert transaction was used
    mock_db.transaction.assert_called_once()

    # Get the transaction function and verify SQL
    transaction_fn = mock_db.transaction.call_args[0][0]
    conn = asyncio.run(transaction_fn()).__aenter__.return_value
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "billing_wallet_balances" in sql
    assert "subscriber_id" in sql
    assert "msisdn" in sql
    assert "balance_paise" in sql


def test_load_balances_seeds_valkey_keys(mock_db, mock_cache):
    """Warm-up seeds balance:{msisdn} keys via cache.set_many (Task 7)."""
    asyncio.run(load_balances_from_postgres(mock_db, mock_cache))

    # Assert set_many was called with correct keys
    mock_cache.set_many.assert_called_once()
    call_args = mock_cache.set_many.call_args
    balance_dict = call_args[0][0]

    # Assert balance:{msisdn} keys with correct values
    assert "balance:9876543210" in balance_dict
    assert balance_dict["balance:9876543210"] == 100000
    assert "balance:9876543211" in balance_dict
    assert balance_dict["balance:9876543211"] == 50000


def test_load_balances_builds_subscriber_to_msisdn_index(mock_db, mock_cache):
    """Warm-up builds subscriber_id → msisdn index (Task 7)."""
    state = asyncio.run(load_balances_from_postgres(mock_db, mock_cache))

    # Assert subscriber_to_msisdn index built
    assert state.subscriber_to_msisdn["0192a4d0-1234-7000-8000-000000000abc"] == "9876543210"
    assert state.subscriber_to_msisdn["0192a4d0-9999-7000-8000-000000000def"] == "9876543211"

    # Assert reverse msisdn_to_subscriber also built
    assert state.msisdn_to_subscriber["9876543210"] == "0192a4d0-1234-7000-8000-000000000abc"
    assert state.msisdn_to_subscriber["9876543211"] == "0192a4d0-9999-7000-8000-000000000def"


def test_load_balances_returns_count(mock_db, mock_cache):
    """Warm-up returns count of balances seeded (Task 7)."""
    state = asyncio.run(load_balances_from_postgres(mock_db, mock_cache))

    assert state.count == 2


def test_load_balances_empty_table_returns_empty_state(mock_db, mock_cache):
    """Empty billing_wallet_balances → empty warm-up state."""

    # Modify mock to return empty result
    async def mock_transaction():
        async def yield_conn():
            conn = AsyncMock()
            cur = AsyncMock()
            cur.fetchall.return_value = []
            conn.execute.return_value = cur
            yield conn

        return yield_conn()

    mock_db.transaction = mock_transaction

    state = asyncio.run(load_balances_from_postgres(mock_db, mock_cache))

    assert state.count == 0
    assert len(state.subscriber_to_msisdn) == 0
    assert len(state.msisdn_to_subscriber) == 0
    mock_cache.set_many.assert_not_called()  # no keys to set
