"""Unit tests for the ValkeyAdapter dedup primitives (Story 2.2, Task 1).

No live cache: the underlying valkey client is mocked. The high-value assertions
are the ``SET ... NX EX`` shape (the dedup decision, ARCH-5) and ``INCR``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from adapters.redis import ValkeyAdapter
from core.protocols.cache import CacheProtocol


def _adapter(client: AsyncMock) -> ValkeyAdapter:
    """Build an adapter wired to a mocked valkey client."""
    adapter = ValkeyAdapter("redis://localhost:6379")
    adapter._client = client
    return adapter


def test_valkey_adapter_satisfies_cache_protocol() -> None:
    """ValkeyAdapter is a structural match for CacheProtocol (DI seam)."""
    assert isinstance(ValkeyAdapter("redis://localhost:6379"), CacheProtocol)


async def test_set_nx_returns_true_when_newly_set() -> None:
    """SET NX truthy return → first sight → set_nx True."""
    client = AsyncMock()
    client.set.return_value = True
    adapter = _adapter(client)

    result = await adapter.set_nx("dedup:abc", "1", ex=86400)

    assert result is True
    client.set.assert_awaited_once_with("dedup:abc", "1", ex=86400, nx=True)


async def test_set_nx_returns_false_when_key_existed() -> None:
    """SET NX returns None (key existed) → duplicate → set_nx False."""
    client = AsyncMock()
    client.set.return_value = None
    adapter = _adapter(client)

    result = await adapter.set_nx("dedup:abc", "1", ex=86400)

    assert result is False


async def test_set_nx_sends_nx_and_24h_ex_flags() -> None:
    """The dedup guard relies on both NX and EX=86400s being sent (ARCH-5)."""
    client = AsyncMock()
    client.set.return_value = True
    adapter = _adapter(client)

    await adapter.set_nx("dedup:id-1", "1", ex=86400)

    _, kwargs = client.set.await_args
    assert kwargs["nx"] is True
    assert kwargs["ex"] == 86400


async def test_incr_returns_new_value() -> None:
    """INCR returns the post-increment value (int)."""
    client = AsyncMock()
    client.incr.return_value = 7
    adapter = _adapter(client)

    result = await adapter.incr("deduplicated")

    assert result == 7
    client.incr.assert_awaited_once_with("deduplicated")


async def test_ping_returns_false_on_failure() -> None:
    """Ping must never raise — a down cache yields False (readiness-safe)."""
    client = AsyncMock()
    client.ping.side_effect = ConnectionError("down")
    adapter = _adapter(client)

    assert await adapter.ping() is False
