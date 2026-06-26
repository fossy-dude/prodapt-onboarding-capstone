"""Integration test: chat context roundtrip against real Valkey (Story 5.4; AC #3).

Starts a Valkey (Redis-compatible) container and exercises the context module's
save/load roundtrip, sliding-window eviction and TTL re-set through the real
:class:`adapters.redis.ValkeyAdapter` (no fakes).

Marked ``slow`` + ``integration`` and skipped when ``DOCKER_HOST`` is unset (the
container runtime is not available — e.g. rootless Podman in CI). Run with
``pytest --run-slow`` (or ``--run-integration``) when a runtime is available.
"""

from __future__ import annotations

import os
import socket
import time

import pytest

from adapters.redis import ValkeyAdapter
from agents.support.context import (
    CHAT_CONTEXT_TTL_SECONDS,
    MAX_CONTEXT_TURNS,
    context_key,
    load_context,
    save_turn,
)

# Requires a container runtime (rootless Podman/Docker). Skipped by default via
# the slow/integration marks AND the DOCKER_HOST guard.
pytestmark = [pytest.mark.slow, pytest.mark.integration]

if not os.environ.get("DOCKER_HOST"):
    pytest.skip("DOCKER_HOST not set — Valkey testcontainer unavailable", allow_module_level=True)


@pytest.fixture(scope="module")
def valkey_url() -> str:
    """Start a Valkey container and return its redis:// URL."""
    from testcontainers.core.generic import DockerContainer

    container = DockerContainer("valkey/valkey:7.2")
    container.with_exposed_ports(6379)
    with container as c:
        port = int(c.get_exposed_port(6379))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        yield f"redis://127.0.0.1:{port}"


@pytest.fixture
async def cache(valkey_url: str) -> ValkeyAdapter:
    """Provide a fresh ValkeyAdapter per test; close it on teardown."""
    adapter = ValkeyAdapter(valkey_url)
    yield adapter  # type: ignore[misc]
    await adapter.close()


async def test_context_save_load_roundtrip(cache: ValkeyAdapter) -> None:
    await save_turn(cache, "sess-rt", "user", "what is my balance?")
    await save_turn(cache, "sess-rt", "assistant", "Your balance is ₹50.00.")

    loaded = await load_context(cache, "sess-rt")

    assert loaded == [
        {"role": "user", "content": "what is my balance?"},
        {"role": "assistant", "content": "Your balance is ₹50.00."},
    ]


async def test_context_sliding_window_evicts_oldest(cache: ValkeyAdapter) -> None:
    for i in range(MAX_CONTEXT_TURNS + 1):
        await save_turn(cache, "sess-win", "user", f"msg-{i}")

    raw = await cache.hgetall(context_key("sess-win"))
    assert len(raw) == MAX_CONTEXT_TURNS  # only 10 HASH fields survive

    loaded = await load_context(cache, "sess-win")
    assert len(loaded) == MAX_CONTEXT_TURNS
    assert loaded[0] == {"role": "user", "content": "msg-1"}  # msg-0 evicted


async def test_context_ttl_is_set_with_two_hour_window(cache: ValkeyAdapter) -> None:
    await save_turn(cache, "sess-ttl", "user", "hi")

    ttl = await cache._client.ttl(context_key("sess-ttl"))
    # TTL is reset on every write to CHAT_CONTEXT_TTL_SECONDS (7200s); allow a
    # small margin for the round-trip.
    assert CHAT_CONTEXT_TTL_SECONDS - 5 <= ttl <= CHAT_CONTEXT_TTL_SECONDS
