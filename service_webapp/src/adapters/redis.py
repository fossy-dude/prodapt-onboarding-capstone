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
    """Async Valkey adapter. ``PING`` is the readiness check; set/get/delete support step-up OTP."""

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
        """SET key value EX ex — used for step-up OTP storage (§1.7.3)."""
        await self._client.set(key, value, ex=ex)

    async def get_str(self, key: str) -> str | None:
        """GET key and decode bytes → str, or ``None`` if absent/expired."""
        raw = await self._client.get(key)
        return raw.decode("utf-8") if raw is not None else None

    async def delete(self, key: str) -> None:
        """DEL key — called after a step-up OTP is consumed (§1.7.3)."""
        await self._client.delete(key)

    async def set_balance(self, msisdn: str, paise: int) -> None:
        """SET ``balance:{msisdn} = paise`` with no TTL (persistent counter — §1.7.3).

        Stored as an integer so the cdr-pipeline consumer can ``INCRBY`` it directly.
        Seeded at SIM activation to the plan's initial wallet credit.
        """
        await self._client.set(f"balance:{msisdn}", paise)

    async def close(self) -> None:
        """Close the underlying client (best-effort)."""
        try:
            await self._client.aclose()
        except Exception:
            pass
