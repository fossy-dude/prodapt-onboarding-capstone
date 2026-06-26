"""Psycopg3 async adapter implementing :class:`DatabaseProtocol` (Story 2.3).

Mirrors ``service_webapp/src/adapters/postgres.py`` — ``AsyncConnectionPool``
backed adapter with ``ping`` (readiness), ``transaction`` (multi-statement work
for flush upserts, ledger inserts, warm-up), and ``close``. Connects as
``sboai_app`` (the app_rw role; Story 1.2's roles config).

Warm-up queries the ``billing_wallet_balances`` table (< 5s for 300K rows per
Story 2.3 AC #5) via the transaction context.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import psycopg.conninfo
from psycopg_pool import AsyncConnectionPool

from core.protocols.db import DatabaseProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection

    from core.config import DatabaseSettings

_CONNECT_TIMEOUT_SECONDS = 2


def conninfo_from(db: DatabaseSettings) -> str:
    """Build a libpq conninfo string from the nested DB settings.

    Uses ``psycopg.conninfo.make_conninfo`` so special characters in the
    password or username (spaces, single-quotes, backslashes, equals signs)
    are properly quoted and never break the libpq parser.
    """
    return psycopg.conninfo.make_conninfo(
        host=db.host,
        port=db.port,
        dbname=db.name,
        user=db.user,
        password=db.password.get_secret_value(),
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
    )


class Psycopg3AsyncAdapter(DatabaseProtocol):
    """Async Postgres adapter backed by a ``psycopg`` :class:`AsyncConnectionPool`."""

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        timeout: float = 2.0,
    ) -> None:
        # ``open=False`` defers the first connection so constructing the adapter
        # (e.g. at app boot) never blocks or fails when Postgres is briefly down.
        # ``timeout`` bounds connection acquisition so a hung host can't stall
        # readiness or warm-up; a refused port (the common down case) fails instantly.
        self._pool = AsyncConnectionPool(
            conninfo,
            open=False,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
        )

    async def ping(self) -> bool:
        """``SELECT 1`` against the pool. Never raises — returns ``False`` on failure."""
        try:
            await self._pool.open()
        except Exception:
            return False
        try:
            async with self._pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Yield a pooled connection inside an explicit transaction.

        Used by warm-up (load_balances_from_postgres) and the flusher (wallet upserts
        + ledger inserts). The pool is opened idempotently so first use after boot
        does not fail; the transaction commits on clean exit and rolls back on any
        exception.
        """
        await self._pool.open()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                yield conn

    async def close(self) -> None:
        """Close the underlying pool (safe if it was never opened)."""
        try:
            await self._pool.close()
        except Exception:
            pass
