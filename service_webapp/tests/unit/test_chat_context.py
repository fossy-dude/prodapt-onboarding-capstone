"""Unit tests for the Valkey-backed chat context (Story 5.4; AC #3).

Exercises the sliding-window HASH store with an in-memory fake cache (no real
Valkey needed). The slow/integration roundtrip against a real Valkey container
lives in ``tests/integration`` (testcontainers) and is skipped by default.
"""

from __future__ import annotations

import json

import pytest

from agents.support.context import (
    CHAT_CONTEXT_TTL_SECONDS,
    MAX_CONTEXT_TURNS,
    context_key,
    load_context,
    save_turn,
)


class FakeHashCache:
    """In-memory stand-in for the Valkey HASH surface the context module uses."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str], *, ex: int | None = None) -> None:
        self.hashes[key] = dict(mapping)
        if ex is not None:
            self.expires[key] = ex

    async def delete(self, key: str) -> None:
        self.hashes.pop(key, None)
        self.expires.pop(key, None)


@pytest.fixture
def cache() -> FakeHashCache:
    return FakeHashCache()


async def test_load_context_empty_for_fresh_session(cache: FakeHashCache) -> None:
    assert await load_context(cache, "sess-1") == []


async def test_save_then_load_roundtrip(cache: FakeHashCache) -> None:
    await save_turn(cache, "sess-1", "user", "what is my balance?")
    await save_turn(cache, "sess-1", "assistant", "Your balance is ₹50.00.")

    loaded = await load_context(cache, "sess-1")

    assert loaded == [
        {"role": "user", "content": "what is my balance?"},
        {"role": "assistant", "content": "Your balance is ₹50.00."},
    ]


async def test_save_sets_two_hour_ttl(cache: FakeHashCache) -> None:
    await save_turn(cache, "sess-1", "user", "hi")

    assert cache.expires[context_key("sess-1")] == CHAT_CONTEXT_TTL_SECONDS == 7200


async def test_ttl_resets_on_each_write(cache: FakeHashCache) -> None:
    """The 2h window slides from the last message — EXPIRE is re-set every save (ARCH-5)."""
    await save_turn(cache, "sess-1", "user", "first")
    first_expiry_key = context_key("sess-1")
    assert first_expiry_key in cache.expires

    await save_turn(cache, "sess-1", "assistant", "second")
    # Re-written (delete + hset) so the expiry is set again on the fresh key.
    assert cache.expires[first_expiry_key] == CHAT_CONTEXT_TTL_SECONDS


async def test_sliding_window_evicts_oldest_after_max(cache: FakeHashCache) -> None:
    """Adding the (MAX+1)th turn evicts the oldest — fields stay bounded at MAX."""
    for i in range(MAX_CONTEXT_TURNS + 1):
        await save_turn(cache, "sess-1", "user", f"msg-{i}")

    key = context_key("sess-1")
    # Only MAX fields survive, re-indexed turn_0..turn_{MAX-1}.
    assert len(cache.hashes[key]) == MAX_CONTEXT_TURNS
    assert set(cache.hashes[key]) == {f"turn_{i}" for i in range(MAX_CONTEXT_TURNS)}

    loaded = await load_context(cache, "sess-1")
    assert len(loaded) == MAX_CONTEXT_TURNS
    # The very first message ("msg-0") was evicted; the window now starts at msg-1.
    assert loaded[0] == {"role": "user", "content": "msg-1"}
    assert loaded[-1] == {"role": "user", "content": f"msg-{MAX_CONTEXT_TURNS}"}


async def test_window_keeps_last_ten_across_many_turns(cache: FakeHashCache) -> None:
    for i in range(25):
        await save_turn(cache, "sess-1", "user", f"msg-{i}")

    loaded = await load_context(cache, "sess-1")
    assert len(loaded) == MAX_CONTEXT_TURNS
    # The last 10 messages are msg-15..msg-24.
    assert loaded[0] == {"role": "user", "content": "msg-15"}
    assert loaded[-1] == {"role": "user", "content": "msg-24"}


async def test_context_isolated_per_session(cache: FakeHashCache) -> None:
    await save_turn(cache, "sess-A", "user", "A1")
    await save_turn(cache, "sess-B", "user", "B1")

    assert await load_context(cache, "sess-A") == [{"role": "user", "content": "A1"}]
    assert await load_context(cache, "sess-B") == [{"role": "user", "content": "B1"}]


async def test_load_skips_malformed_fields(cache: FakeHashCache) -> None:
    """A corrupt turn must not break loading the rest of the conversation."""
    key = context_key("sess-1")
    cache.hashes[key] = {
        "turn_0": json.dumps({"role": "user", "content": "good"}),
        "turn_1": "not-json",
        "turn_2": json.dumps({"role": "assistant", "content": "also good"}),
        "not_a_turn": json.dumps({"role": "user", "content": "ignored"}),
    }

    loaded = await load_context(cache, "sess-1")

    assert loaded == [
        {"role": "user", "content": "good"},
        {"role": "assistant", "content": "also good"},
    ]
