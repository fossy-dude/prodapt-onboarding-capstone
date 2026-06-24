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

    async def get_balance(self, msisdn: str) -> int | None:
        """GET ``balance:{msisdn}`` as integer paise; ``None`` if key absent (cold cache)."""
        raw = await self._client.get(f"balance:{msisdn}")
        return int(raw) if raw is not None else None

    async def incr_balance(self, msisdn: str, delta_paise: int) -> int:
        """INCRBY ``balance:{msisdn} +delta_paise`` and return new value (Story 3.5).

        Used for crediting wallet after recharge. The cdr-pipeline consumer uses
        INCRBY with negative delta for deductions (Story 2-3). This mirrors the
        deduction writer's INCRBY contract but for credits (positive delta).

        Returns the new balance after increment.
        """
        return await self._client.incrby(f"balance:{msisdn}", delta_paise)

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        """Atomically INCR key and set TTL if key is new; return new counter value.

        Uses a Lua script so INCR and EXPIRE are executed atomically in a single
        round-trip. The TTL is only set on the first increment (NX semantics) to
        avoid resetting the window on every request.
        """
        lua_script = (
            "local c = redis.call('INCR', KEYS[1])\nif c == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end\nreturn c"
        )
        result = await self._client.eval(lua_script, 1, key, ttl_seconds)  # type: ignore[call-arg]
        return int(result)

    async def hset(self, key: str, mapping: dict[str, str], *, ex: int | None = None) -> None:
        """HSET ``key`` from mapping; optionally EXPIRE after ``ex`` seconds (Story 4.4)."""
        await self._client.hset(key, mapping=mapping)  # type: ignore[arg-type]
        if ex is not None:
            await self._client.expire(key, ex)

    async def hgetall(self, key: str) -> dict[str, str]:
        """HGETALL ``key``; returns ``{}`` if absent (Story 4.4)."""
        raw: dict[bytes, bytes] = await self._client.hgetall(key)  # type: ignore[assignment]
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in raw.items()}

    async def close(self) -> None:
        """Close the underlying client (best-effort)."""
        try:
            await self._client.aclose()
        except Exception:
            pass
