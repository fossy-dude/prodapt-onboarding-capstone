"""Database port (architecture §1.12.1 dependency-inversion seam).

Business logic and the readiness check depend on this Protocol, never the
concrete psycopg pool. Later stories extend it; for Story 1.4 only the
connectivity check is needed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DatabaseProtocol(Protocol):
    """Minimal database port: a connectivity check for the readiness probe."""

    async def ping(self) -> bool:
        """Return ``True`` if the database is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so ``/ready`` can
        report it cleanly instead of erroring.
        """
        ...
