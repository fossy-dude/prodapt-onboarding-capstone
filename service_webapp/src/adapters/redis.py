"""Valkey (redis-protocol) async adapter implementing :class:`CacheProtocol`.

Named ``redis.py`` because the Valkey client speaks the Redis protocol and the
container/service is referred to as the cache/redis throughout the architecture.
Minimal — just enough for the ``/ready`` ping.
"""

from __future__ import annotations

import valkey.asyncio as avalkey

from core.protocols.cache import CacheProtocol

# Bound so a hung/blackholed host can never stall the readiness probe.
_SOCKET_TIMEOUT_SECONDS = 2


class ValkeyAdapter(CacheProtocol):
    """Async Valkey adapter. ``PING`` is the readiness check."""

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

    async def close(self) -> None:
        """Close the underlying client (best-effort)."""
        try:
            await self._client.aclose()
        except Exception:
            pass
