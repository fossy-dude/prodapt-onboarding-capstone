"""Cache port (architecture §1.12.1 dependency-inversion seam)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheProtocol(Protocol):
    """Cache port: connectivity check + generic string key/value ops for OTP (Story 1.8)."""

    async def ping(self) -> bool:
        """Return ``True`` if the cache (Valkey) is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so ``/ready`` can
        report it cleanly instead of erroring.
        """
        ...

    async def set_str(self, key: str, value: str, ex: int) -> None:
        """Set a string key with an expiry in seconds."""
        ...

    async def get_str(self, key: str) -> str | None:
        """Return the string value for ``key``, or ``None`` if absent/expired."""
        ...

    async def delete(self, key: str) -> None:
        """Delete ``key`` (no-op if absent)."""
        ...
