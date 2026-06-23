"""Unit tests for startup warm-up (Story 2.3, Task 7)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest

from consumer.startup import load_balances_from_postgres

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeCursor:
    """Mimics a psycopg cursor: fetchall/fetchone return seeded rows."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[tuple]:
        return self._rows

    async def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    """Mimics a pooled psycopg AsyncConnection: execute records SQL + returns a cursor."""

    def __init__(self, fetch_rows: list[tuple], executed: list[tuple]) -> None:
        self._fetch_rows = fetch_rows
        self._executed = executed

    async def execute(self, sql: str, *params: object) -> FakeCursor:
        self._executed.append((sql, params))
        return FakeCursor(self._fetch_rows)


class FakeDB:
    """Fake DatabaseProtocol: ``transaction`` yields a FakeConn recording every execute."""

    def __init__(self, fetch_rows: list[tuple] | None = None) -> None:
        self._fetch_rows = fetch_rows or []
        self.executed: list[tuple] = []  # (sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeConn]:
        yield FakeConn(self._fetch_rows, self.executed)

    async def ping(self) -> bool:
        return True


class FakeCache:
    """In-memory CacheProtocol capturing set_many / incr_by / delete calls."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
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
        v = int(self.store.get(key, "0")) + amount
        self.store[key] = str(v)
        return v

    async def set_many(self, mapping: dict[str, int]) -> None:
        self.set_many_calls.append(dict(mapping))
        for k, v in mapping.items():
            self.store[k] = str(v)


_ROWS = [
    ("0192a4d0-1234-7000-8000-000000000abc", "9876543210", 100000),
    ("0192a4d0-9999-7000-8000-000000000def", "9876543211", 50000),
]


def test_load_balances_queries_billing_wallet_balances():
    """Warm-up queries billing_wallet_balances for subscriber_id/msisdn/balance_paise."""
    db = FakeDB(fetch_rows=_ROWS)
    cache = FakeCache()

    asyncio.run(load_balances_from_postgres(db, cache))

    assert len(db.executed) == 1
    sql = db.executed[0][0]
    assert "billing_wallet_balances" in sql
    assert "subscriber_id" in sql
    assert "msisdn" in sql
    assert "balance_paise" in sql


def test_load_balances_seeds_valkey_keys():
    """Warm-up seeds balance:{msisdn} keys via cache.set_many."""
    db = FakeDB(fetch_rows=_ROWS)
    cache = FakeCache()

    asyncio.run(load_balances_from_postgres(db, cache))

    assert len(cache.set_many_calls) == 1
    balance_dict = cache.set_many_calls[0]
    assert balance_dict["balance:9876543210"] == 100000
    assert balance_dict["balance:9876543211"] == 50000
    # Keys landed in the store too
    assert cache.store["balance:9876543210"] == "100000"


def test_load_balances_builds_indices():
    """Warm-up builds subscriber→msisdn and msisdn→subscriber indices."""
    db = FakeDB(fetch_rows=_ROWS)
    cache = FakeCache()

    state = asyncio.run(load_balances_from_postgres(db, cache))

    assert state.subscriber_to_msisdn["0192a4d0-1234-7000-8000-000000000abc"] == "9876543210"
    assert state.subscriber_to_msisdn["0192a4d0-9999-7000-8000-000000000def"] == "9876543211"
    assert state.msisdn_to_subscriber["9876543210"] == "0192a4d0-1234-7000-8000-000000000abc"
    assert state.msisdn_to_subscriber["9876543211"] == "0192a4d0-9999-7000-8000-000000000def"
    assert state.count == 2


def test_load_balances_empty_table_skips_set_many():
    """Empty billing_wallet_balances → empty warm-up state, no set_many call."""
    db = FakeDB(fetch_rows=[])
    cache = FakeCache()

    state = asyncio.run(load_balances_from_postgres(db, cache))

    assert state.count == 0
    assert len(state.subscriber_to_msisdn) == 0
    assert len(state.msisdn_to_subscriber) == 0
    assert cache.set_many_calls == []  # no keys to set
