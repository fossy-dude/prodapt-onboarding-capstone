"""Database port (Story 2.3; architecture §1.12.1 dependency-inversion seam).

Mirrors ``service_webapp`` core/protocols/db.py. Business logic and readiness
depend on this Protocol, never the concrete psycopg pool. The ``transaction``
context manager yields a pooled connection inside an explicit transaction for
multi-statement units of work (flush upserts, ledger inserts, warm-up queries).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from psycopg import AsyncConnection


@runtime_checkable
class DatabaseProtocol(Protocol):
    """Database port: connectivity check + transactional multi-statement work.

    ``ping`` is for the readiness probe (Story 1.4). ``transaction`` yields a
    pooled ``AsyncConnection`` inside an explicit transaction; repositories use
    it for flush upserts, ledger inserts, and warm-up queries. Commits on clean
    exit, rolls back on exception, and opens the pool idempotently.
    """

    async def ping(self) -> bool:
        """Return ``True`` if the database is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so callers can
        report it cleanly instead of erroring.
        """
        ...

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Return an async context manager yielding a pooled ``AsyncConnection``.

        Implementations use ``@asynccontextmanager`` so the method is called and
        the result entered with ``async with``::

            async with db.transaction() as conn:
                await conn.execute("SELECT ...")
                # all-or-nothing transaction
        """
        ...

    async def close(self) -> None:
        """Close the underlying pool (safe if never opened)."""
        ...
