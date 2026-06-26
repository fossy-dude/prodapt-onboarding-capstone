"""Database port (architecture §1.12.1 dependency-inversion seam).

Business logic and the readiness check depend on this Protocol, never the
concrete psycopg pool. Later stories extend it; for Story 1.4 only the
connectivity check is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from psycopg import AsyncConnection


@runtime_checkable
class DatabaseProtocol(Protocol):
    """Minimal database port: connectivity check + transactional connection.

    The ``transaction`` seam is exercised by domain repositories (Story 3.x) and
    the Support Agent tools (Story 5.4); it yields a pooled connection inside an
    explicit, all-or-nothing transaction. Later stories extend this port further.
    """

    async def ping(self) -> bool:
        """Return ``True`` if the database is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so ``/ready`` can
        report it cleanly instead of erroring.
        """
        ...

    def connection(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Yield a pooled connection for SELECT-only reads (no explicit transaction).

        CQRS read side (ARCH-4). Callers must not mutate on a connection yielded here;
        use :meth:`transaction` for writes so they commit.
        """
        ...

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Yield a pooled connection inside an explicit transaction (commit/rollback)."""
        ...
