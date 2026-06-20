"""Cache port (architecture §1.12.1 dependency-inversion seam)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheProtocol(Protocol):
    """Minimal cache port: a connectivity check for the readiness probe."""

    async def ping(self) -> bool:
        """Return ``True`` if the cache (Valkey) is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so ``/ready`` can
        report it cleanly instead of erroring.
        """
        ...
