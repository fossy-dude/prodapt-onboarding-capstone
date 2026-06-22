"""Async Valkey adapter implementing :class:`CacheProtocol` (Story 2.2).

Mirrors ``service_webapp/src/adapters/redis.py`` (same ``valkey.asyncio.from_url``
shape plus ``ping``/``set_str``/``get_str``/``delete``/``close``) and adds the
two primitives the CDR consumer needs: ``set_nx`` (``SET ... NX EX``) for the
:mod:`consumer.dedup` guard, and ``incr`` for the balance write buffer
(Story 2.3). Named ``redis.py`` because Valkey speaks the Redis protocol and the
service is referred to as the cache/redis throughout the architecture.
"""

from __future__ import annotations

import valkey.asyncio as avalkey

from core.protocols.cache import CacheProtocol

# Bound so a hung/blackholed host can never stall a hot-path dedup check.
_SOCKET_TIMEOUT_SECONDS = 2


class ValkeyAdapter(CacheProtocol):
    """Async Valkey adapter.

    ``PING`` is the readiness check; ``set_str``/``get_str``/``delete`` cover
    generic string ops; ``set_nx`` is the dedup decision; ``incr`` the counter
    primitive.
    """

    def __init__(self, url: str) -> None:
        self._client = avalkey.from_url(
            url,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        )

    async def ping(self) -> bool:
        """``PING`` the cache. Never raises — returns ``False`` on failure."""
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def set_str(self, key: str, value: str, ex: int) -> None:
        """SET key value EX ex."""
        await self._client.set(key, value, ex=ex)

    async def get_str(self, key: str) -> str | None:
        """GET key and decode bytes → str, or ``None`` if absent/expired."""
        raw = await self._client.get(key)
        return raw.decode("utf-8") if raw is not None else None

    async def delete(self, key: str) -> None:
        """DEL key (no-op if absent)."""
        await self._client.delete(key)

    async def set_nx(self, key: str, value: str, ex: int) -> bool:
        """``SET key value NX EX ex`` → ``True`` if newly set, ``False`` if it existed.

        The atomic ``NX`` is the dedup decision: a ``True`` return means first
        sight, ``False`` means the key was already present within its TTL
        (duplicate). Mirrors the ``SET ... NX EX`` mandated by ARCH-5.
        """
        result = await self._client.set(key, value, ex=ex, nx=True)
        return bool(result)

    async def incr(self, key: str) -> int:
        """``INCR key`` → the value after incrementing."""
        return int(await self._client.incr(key))

    async def close(self) -> None:
        """Close the underlying client (best-effort)."""
        try:
            await self._client.aclose()
        except Exception:
            pass
