"""Psycopg3 async adapter implementing :class:`DatabaseProtocol` (Story 1.4; §1.12.1).

Minimal — just enough for the ``/ready`` ping (``SELECT 1``). The full data-access
adapter (repositories, transactions) is fleshed out in later domain stories; do
not over-build here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg_pool import AsyncConnectionPool

from core.protocols.db import DatabaseProtocol

if TYPE_CHECKING:
    # Used only in the ``conninfo_from`` annotation.
    from core.config import DatabaseSettings

# Bound so a hung/blackholed host can never stall the readiness probe. A refused
# port (the common down case) fails instantly regardless.
_CONNECT_TIMEOUT_SECONDS = 2


def conninfo_from(db: DatabaseSettings) -> str:
    """Build a libpq conninfo string from the nested DB settings."""
    return (
        f"host={db.host} port={db.port} dbname={db.name} "
        f"user={db.user} password={db.password} connect_timeout={_CONNECT_TIMEOUT_SECONDS}"
    )


class Psycopg3AsyncAdapter(DatabaseProtocol):
    """Async Postgres adapter backed by a ``psycopg`` :class:`AsyncConnectionPool`."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 5, timeout: float = 2.0) -> None:
        # ``open=False`` defers the first connection so constructing the adapter
        # (e.g. at app boot) never blocks or fails when Postgres is briefly down.
        # ``timeout`` bounds connection acquisition so a hung host can't stall
        # ``/ready``; a refused port (the common down case) fails instantly.
        self._pool = AsyncConnectionPool(conninfo, open=False, min_size=min_size, max_size=max_size, timeout=timeout)

    async def ping(self) -> bool:
        """``SELECT 1`` against the pool. Never raises — returns ``False`` on failure."""
        try:
            # Idempotent open: a second call raises PoolError, which we ignore.
            await self._pool.open()
        except Exception:
            pass
        try:
            async with self._pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying pool (safe if it was never opened)."""
        try:
            await self._pool.close()
        except Exception:
            pass
