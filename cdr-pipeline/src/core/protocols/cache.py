"""Cache port (architecture §1.12.1 dependency-inversion seam, ARCH-15).

The consumer's dedup guard (:mod:`consumer.dedup`) depends on this Protocol,
never the concrete Valkey adapter — mirroring ``service_webapp``
``core/protocols/cache.py``. All operations are async (ARCH-15: no blocking I/O
in the pipeline).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheProtocol(Protocol):
    """Cache port: connectivity, string ops, and the dedup primitives.

    ``set_nx`` (``SET key value NX EX``) is the dedup decision primitive
    (Story 2.2, ARCH-5): it returns ``True`` when the key was freshly set
    (first sight) and ``False`` when it already existed (duplicate). ``incr``
    is exposed for the in-process dedup metric and the Story 2.3 balance
    ``INCRBY`` write buffer.
    """

    async def ping(self) -> bool:
        """Return ``True`` if the cache (Valkey) is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so callers can
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

    async def set_nx(self, key: str, value: str, ex: int) -> bool:
        """``SET key value NX EX ex`` — atomic set-if-absent with a TTL.

        Returns
        -------
        bool
            ``True`` when the key was newly set (first sight),
            ``False`` when it already existed (the ``NX`` guard failed → duplicate).
        """
        ...

    async def incr(self, key: str) -> int:
        """``INCR key`` — atomically increment and return the new value."""
        ...
