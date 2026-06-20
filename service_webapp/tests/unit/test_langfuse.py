"""Unit tests for the LangFuse client singleton + ``@trace_agent`` decorator.

The whole point of AC #4 is that everything below runs WITHOUT a live LangFuse
server: the disabled path is a true no-op (no client construction), and the
enabled path exercises a mocked client so we assert the recorded fields without
any network. (Story 1.5; architecture §1.11.8 — unit tests only.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from core.config import settings
from core.observability.langfuse import (
    current_trace_id,
    get_langfuse_client,
    set_trace_id,
    set_trace_usage,
    trace_agent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
def _reset_langfuse_state() -> AsyncIterator[None]:
    """Isolate each test: disabled singleton cache + contextvars + settings flag.

    The module-level singleton caches the client and reads ``settings`` at call
    time, so tests toggle ``settings.langfuse_enabled`` and must clear the cache
    between cases (and restore the disabled default for the rest of the suite).
    """
    from core.observability.langfuse import _reset_langfuse_client_for_tests

    _reset_langfuse_client_for_tests()
    set_trace_id(None)
    set_trace_usage(None)
    settings.langfuse_enabled = False
    yield
    _reset_langfuse_client_for_tests()
    set_trace_id(None)
    set_trace_usage(None)
    settings.langfuse_enabled = False


def _wire_mock_client() -> tuple[MagicMock, MagicMock]:
    """Build a mock Langfuse client for the observation context manager.

    The CM yields a known ``observation`` mock so call assertions are unambiguous.
    """
    client = MagicMock(name="langfuse_client")
    observation = MagicMock(name="observation")
    # ``with client.start_as_current_observation(...) as observation`` binds here
    # (MagicMock's __enter__ returns cm.__enter__.return_value, not cm.return_value).
    client.start_as_current_observation.return_value.__enter__.return_value = observation
    return client, observation


# ── get_langfuse_client(): disabled path (AC #2, #4) ────────────────────────────


def test_get_client_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """LANGFUSE_ENABLED=false → client is None (callers short-circuit, no network)."""
    # A real Langfuse() must never be constructed — spy to prove it.
    spy = MagicMock()
    monkeypatch.setattr("core.observability.langfuse.Langfuse", spy)
    settings.langfuse_enabled = False

    assert get_langfuse_client() is None
    spy.assert_not_called()


def test_get_client_caches_none_when_disabled() -> None:
    """Repeated calls while disabled keep returning None (no latent construction)."""
    settings.langfuse_enabled = False
    assert get_langfuse_client() is None
    assert get_langfuse_client() is None


# ── get_langfuse_client(): enabled singleton identity (AC #2) ───────────────────


def test_get_client_is_singleton_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled → a single Langfuse() is constructed once and reused (singleton)."""
    constructed: list[Any] = []
    captured: dict[str, Any] = {}

    def fake_ctor(**kwargs: object) -> Any:
        captured.update(kwargs)
        instance: Any = MagicMock(name="langfuse_instance")
        constructed.append(instance)
        return instance

    monkeypatch.setattr("core.observability.langfuse.Langfuse", fake_ctor)
    settings.langfuse_enabled = True

    first = get_langfuse_client()
    second = get_langfuse_client()

    assert first is second
    assert len(constructed) == 1  # constructor invoked exactly once
    # Built from settings, never hard-coded (architecture §1.11.1).
    assert captured == {
        "host": settings.langfuse_host,
        "public_key": settings.langfuse_public_key,
        "secret_key": settings.langfuse_secret_key,
    }


# ── @trace_agent: disabled pass-through (AC #3, #4) ─────────────────────────────


async def test_trace_agent_disabled_returns_value_without_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled → wrapped fn returns its real value and the client is never touched."""
    spy = MagicMock()
    monkeypatch.setattr("core.observability.langfuse.Langfuse", spy)
    settings.langfuse_enabled = False

    @trace_agent("noop_agent", model="gpt-4o")
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(2, 3) == 5
    spy.assert_not_called()  # zero LangFuse overhead, no client construction


async def test_trace_agent_disabled_propagates_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled → the wrapper is transparent: exceptions pass through unchanged."""
    monkeypatch.setattr("core.observability.langfuse.Langfuse", MagicMock())
    settings.langfuse_enabled = False

    @trace_agent("boom_agent")
    async def boom() -> None:
        raise RuntimeError("agent failed")

    with pytest.raises(RuntimeError, match="agent failed"):
        await boom()


def test_trace_agent_disabled_preserves_signature() -> None:
    """functools.wraps keeps __name__/__wrapped__ so the primitive is transparent."""
    settings.langfuse_enabled = False

    @trace_agent()
    async def my_agent(query: str) -> str:
        return query

    assert my_agent.__name__ == "my_agent"
    assert hasattr(my_agent, "__wrapped__")


# ── @trace_agent: enabled recording (AC #3) ─────────────────────────────────────


async def test_trace_agent_enabled_records_full_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled + mocked client → one observation records name/input/output/model/usage."""
    client, observation = _wire_mock_client()
    monkeypatch.setattr("core.observability.langfuse.get_langfuse_client", lambda: client)
    settings.langfuse_enabled = True

    # Correlate with the OTEL trace_id (architecture §1.13.7).
    set_trace_id("otel-trace-abc")
    # Token usage comes from the LLM response (FR-72); bound for the in-flight call.
    set_trace_usage({"input": 120, "output": 45})

    @trace_agent("recharge_agent", model="gpt-4o")
    async def recharge(plan_id: str, amount: int) -> str:
        return f"recharged-{plan_id}-{amount}"

    result = await recharge("plan-7", amount=99)
    assert result == "recharged-plan-7-99"

    # Exactly one observation opened, as a generation, with name + model + PII-safe
    # input + the OTEL trace_id in metadata.
    client.start_as_current_observation.assert_called_once()
    call_kwargs = client.start_as_current_observation.call_args.kwargs
    assert call_kwargs["name"] == "recharge_agent"
    assert call_kwargs["as_type"] == "generation"
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["input"] == {"args": ["plan-7"], "kwargs": {"amount": 99}}
    assert call_kwargs["metadata"] == {"trace_id": "otel-trace-abc"}

    # The observation received the return value + token usage (FR-72).
    observation.update.assert_called_once_with(output="recharged-plan-7-99", usage_details={"input": 120, "output": 45})


async def test_trace_agent_enabled_defaults_name_to_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No explicit name → the wrapped function's __name__ is the trace name."""
    client, _ = _wire_mock_client()
    monkeypatch.setattr("core.observability.langfuse.get_langfuse_client", lambda: client)
    settings.langfuse_enabled = True

    @trace_agent(model="claude-sonnet")
    async def recommend_plan() -> str:
        return "plan-pro"

    assert await recommend_plan() == "plan-pro"
    call_kwargs = client.start_as_current_observation.call_args.kwargs
    assert call_kwargs["name"] == "recommend_plan"
    assert call_kwargs["model"] == "claude-sonnet"


async def test_trace_agent_enabled_without_usage_omits_usage_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No usage bound → update() still records output but omits usage_details."""
    client, observation = _wire_mock_client()
    monkeypatch.setattr("core.observability.langfuse.get_langfuse_client", lambda: client)
    settings.langfuse_enabled = True

    @trace_agent("plain_agent")
    async def run() -> str:
        return "done"

    assert await run() == "done"
    observation.update.assert_called_once_with(output="done")


async def test_trace_agent_enabled_marks_error_observation_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrapped fn raises → observation flagged ERROR, exception re-raised (not swallowed)."""
    client, observation = _wire_mock_client()
    monkeypatch.setattr("core.observability.langfuse.get_langfuse_client", lambda: client)
    settings.langfuse_enabled = True

    @trace_agent("failing_agent")
    async def fail() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await fail()

    observation.update.assert_called_once_with(level="ERROR")


def test_current_trace_id_roundtrip() -> None:
    """set_trace_id / current_trace_id propagate the OTEL trace id per context."""
    set_trace_id("trace-xyz")
    assert current_trace_id() == "trace-xyz"
