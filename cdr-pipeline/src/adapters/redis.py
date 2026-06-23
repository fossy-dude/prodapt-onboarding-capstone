"""Async Valkey adapter implementing :class:`CacheProtocol` (Story 2.2).

Mirrors ``service_webapp/src/adapters/redis.py`` (same ``valkey.asyncio.from_url``
shape plus ``ping``/``set_str``/``get_str``/``delete``/``close``) and adds the
two primitives the CDR consumer needs: ``set_nx`` (``SET ... NX EX``) for the
:mod:`consumer.dedup` guard, and ``incr`` for the balance write buffer
(Story 2.3). Named ``redis.py`` because Valkey speaks the Redis protocol and the
service is referred to as the cache/redis throughout the architecture.
"""

from __future__ import annotations

import logging

import valkey.asyncio as avalkey

from core.protocols.cache import CacheProtocol

logger = logging.getLogger("adapters.redis")

# Bound so a hung/blackholed host can never stall a hot-path dedup check.
_SOCKET_TIMEOUT_SECONDS = 2

# How many times set_many retries a chunk whose keys failed (transient connection
# drop mid-pipeline). After this, a partial seed raises so warm-up fails fast.
_SET_MANY_MAX_ATTEMPTS = 3


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

    async def incr_by(self, key: str, amount: int) -> int:
        """``INCRBY key amount`` → the value after incrementing by ``amount``."""
        return int(await self._client.incrby(key, amount))

    async def set_many(self, mapping: dict[str, int]) -> None:
        """Bulk SET multiple integer keys with no expiry (valkey pipeline).

        Chunks into batches of 5000 to avoid oversized pipelines. For 300K rows,
        this keeps memory usage bounded and completes in < 5s (Story 2.3 AC #5).

        A dropped connection mid-pipeline must NOT leave a partially seeded cache
        (those subscribers would then ``INCRBY`` from 0 → silently wrong/negative
        balances). Each command's result is checked; failed chunks are retried, and
        if any keys remain unset after the retries the whole call raises so warm-up
        fails fast instead of corrupting balances.
        """
        if not mapping:
            return

        chunk_size = 5000
        remaining: dict[str, int] = dict(mapping)

        for attempt in range(1, _SET_MANY_MAX_ATTEMPTS + 1):
            if not remaining:
                break
            items = list(remaining.items())
            still_failed: dict[str, int] = {}
            for i in range(0, len(items), chunk_size):
                chunk = items[i : i + chunk_size]
                pipe = self._client.pipeline()
                for k, v in chunk:
                    pipe.set(k, str(v))  # valkey stores as string
                try:
                    results = await pipe.execute()
                except Exception:
                    # Whole pipeline failed — retry every key in this chunk.
                    logger.exception("set_many: pipeline execute failed (attempt %d)", attempt)
                    still_failed.update(chunk)
                    continue
                # Per-command: a successful SET is truthy (True / "OK"); anything
                # else (None, False, or an exception object) is a failed key.
                for (k, v), res in zip(chunk, results, strict=True):
                    if isinstance(res, Exception) or not res:
                        still_failed[k] = v
            remaining = still_failed
            if remaining:
                logger.warning(
                    "set_many: %d keys failed on attempt %d/%d; retrying",
                    len(remaining),
                    attempt,
                    _SET_MANY_MAX_ATTEMPTS,
                )

        if remaining:
            sample = list(remaining)[:3]
            logger.error(
                "set_many: %d keys failed to seed after %d attempts (sample=%s)",
                len(remaining),
                _SET_MANY_MAX_ATTEMPTS,
                sample,
            )
            raise RuntimeError(
                f"set_many: {len(remaining)} of {len(mapping)} balance keys failed to seed "
                f"after {_SET_MANY_MAX_ATTEMPTS} attempts — aborting warm-up to avoid "
                "partially seeded balances (sample keys logged above)"
            )

    async def close(self) -> None:
        """Close the underlying client (best-effort)."""
        try:
            await self._client.aclose()
        except Exception:
            pass
