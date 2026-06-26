"""Unit tests for the Balance Management Agent + balance_lookup tool (Story 5.8 AC #5, #6).

Tests:
- The Balance Management Agent graph reads ``balance:{msisdn}`` from Valkey and
  returns paise (5000 -> 5000); a cold key yields 0; cache-not-wired yields None.
- The ``balance_lookup`` Support Agent tool formats the A2A result into paise +
  INR, and emits the LangFuse ``a2a_balance_agent`` child span (AC #6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agents.support.identity import support_context
from agents.support.tools import balance_lookup, set_support_adapters

if TYPE_CHECKING:
    from typing import Self

# Fixed subscriber used for the identity context (a valid-ish UUIDv7 string).
_SUB = "00000000-0000-7000-8000-000000000000"
_MSISDN = "919876543210"


class _FakeCache:
    """Minimal cache fake exposing only ``get_balance`` (the Balance Agent's need)."""

    def __init__(self, balance: int | None) -> None:
        self._balance = balance

    async def get_balance(self, msisdn: str) -> int | None:
        return self._balance

    async def ping(self) -> bool:
        return True


class _MockLangfuseSpan:
    def __init__(self, name: str, input: dict) -> None:
        self.name = name
        self.input = input

    def update(self, **kwargs: object) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _MockLangfuseClient:
    def __init__(self) -> None:
        self.spans: list[_MockLangfuseSpan] = []

    def start_as_current_observation(self, name: str, as_type: str, input: dict) -> _MockLangfuseSpan:
        span = _MockLangfuseSpan(name, input)
        self.spans.append(span)
        return span


@pytest.fixture(autouse=True)
def _reset_adapters() -> None:
    """Clear the support tool singletons after each test to avoid cross-test leakage."""
    yield
    set_support_adapters(None, None)


class TestBalanceAgentGraph:
    """Direct tests against the Balance Management Agent compiled graph."""

    @pytest.mark.asyncio
    async def test_graph_reads_valkey_balance(self) -> None:
        from agents.balance.graph import balance_graph

        set_support_adapters(_FakeCache(5000), None)
        result = await balance_graph.ainvoke(
            {"msisdn": _MSISDN, "balance_paise": None, "trace_id": "trace-1"},
        )
        assert result["balance_paise"] == 5000

    @pytest.mark.asyncio
    async def test_graph_missing_key_is_zero(self) -> None:
        from agents.balance.graph import balance_graph

        set_support_adapters(_FakeCache(None), None)
        result = await balance_graph.ainvoke(
            {"msisdn": _MSISDN, "balance_paise": None, "trace_id": "trace-1"},
        )
        assert result["balance_paise"] == 0

    @pytest.mark.asyncio
    async def test_graph_cache_not_wired_is_none(self) -> None:
        from agents.balance.graph import balance_graph

        set_support_adapters(None, None)
        result = await balance_graph.ainvoke(
            {"msisdn": _MSISDN, "balance_paise": None, "trace_id": "trace-1"},
        )
        assert result["balance_paise"] is None


class TestBalanceLookupTool:
    """Tests for the balance_lookup Support Agent tool (A2A wrapper)."""

    @pytest.mark.asyncio
    async def test_5000_paise_formats_as_50_inr(self) -> None:
        set_support_adapters(_FakeCache(5000), None)
        with support_context(subscriber_id=_SUB, msisdn=_MSISDN, session_id="sess"):
            result = await balance_lookup.ainvoke({"msisdn": _MSISDN})
        assert result["balance_paise"] == 5000
        assert result["balance_inr"] == "₹50.00"

    @pytest.mark.asyncio
    async def test_missing_key_returns_zero_balance(self) -> None:
        set_support_adapters(_FakeCache(None), None)
        with support_context(subscriber_id=_SUB, msisdn=_MSISDN, session_id="sess"):
            result = await balance_lookup.ainvoke({"msisdn": _MSISDN})
        assert result["balance_paise"] == 0
        assert result["balance_inr"] == "₹0.00"

    @pytest.mark.asyncio
    async def test_emits_a2a_balance_agent_child_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agents.support.tools

        client = _MockLangfuseClient()
        # Inject the mock LangFuse client via the same accessor _traced_tool uses.
        monkeypatch.setattr(agents.support.tools, "get_langfuse_client", lambda: client)
        set_support_adapters(_FakeCache(1500), None)
        with support_context(subscriber_id=_SUB, msisdn=_MSISDN, session_id="sess"):
            result = await balance_lookup.ainvoke({"msisdn": _MSISDN})

        assert result["balance_paise"] == 1500
        # AC #6: the A2A call is traced as a child span (a2a_balance_agent) nested
        # under the balance_lookup tool span.
        tool_names = [span.input.get("tool") for span in client.spans]
        assert "a2a_balance_agent" in tool_names
        assert "balance_lookup" in tool_names
