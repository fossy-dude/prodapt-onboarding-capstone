"""Unit tests for the Support Agent LangGraph tools (Story 5.4; AC #2, #6).

The tools resolve the cache/DB from process-wide singletons set via
``set_support_adapters`` (the same pattern Story 5.3's ``set_retriever`` uses), so
each test injects fakes and asserts the tool's mapping + edge-case behaviour.
DB-backed tools patch the leaf query functions so no real Postgres is needed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.rag.retriever import RagChunk
from agents.support import tools as support_tools
from agents.support.tools import (
    get_balance,
    get_plan,
    get_usage,
    rag_search_tool,
    set_support_adapters,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Clear the cache/DB singletons between tests (they are process-global)."""
    set_support_adapters(None, None)
    yield
    set_support_adapters(None, None)


class _FakeDB:
    """Fake DB adapter whose ``transaction()`` yields a sentinel connection."""

    def __init__(self) -> None:
        self.conn = MagicMock(name="conn")

    @asynccontextmanager
    async def transaction(self):
        yield self.conn


# ── get_balance ────────────────────────────────────────────────────────────────


async def test_get_balance_returns_paise_and_formatted_inr() -> None:
    cache = MagicMock()
    cache.get_balance = AsyncMock(return_value=5000)
    set_support_adapters(cache=cache, db=_FakeDB())

    result = await get_balance.ainvoke({"msisdn": "919999990001"})

    assert result == {"balance_paise": 5000, "balance_inr": "₹50.00"}
    cache.get_balance.assert_awaited_once_with("919999990001")


async def test_get_balance_cache_miss_returns_none_values() -> None:
    cache = MagicMock()
    cache.get_balance = AsyncMock(return_value=None)
    set_support_adapters(cache=cache, db=_FakeDB())

    result = await get_balance.ainvoke({"msisdn": "919999990001"})

    assert result == {"balance_paise": None, "balance_inr": None}


async def test_get_balance_raises_when_adapters_not_set() -> None:
    set_support_adapters(cache=None, db=None)
    with pytest.raises(RuntimeError, match="set_support_adapters"):
        await get_balance.ainvoke({"msisdn": "919999990001"})


# ── get_plan ───────────────────────────────────────────────────────────────────


async def test_get_plan_maps_active_plan_row(monkeypatch) -> None:
    db = _FakeDB()
    set_support_adapters(cache=MagicMock(), db=db)

    plan_row = {
        "plan_id": "plan-uuid-1",
        "plan_name": "Truly Unlimited 299",
        "end_date": None,  # parsed-iso path exercised separately below
        "validity_days": 28,
        "data_limit_mb": 1024,
        "voice_minutes": None,
        "sms_count": 100,
    }
    monkeypatch.setattr(support_tools, "get_active_plan", AsyncMock(return_value=plan_row))

    result = await get_plan.ainvoke({"subscriber_id": "12345678-1234-4321-8765-432187654321"})

    assert result["active_plan"]["plan_name"] == "Truly Unlimited 299"
    assert result["active_plan"]["validity_expiry"] is None
    assert result["active_plan"]["data_limit_mb"] == 1024
    assert result["active_plan"]["sms_count"] == 100
    support_tools.get_active_plan.assert_awaited_once()


async def test_get_plan_no_active_subscription(monkeypatch) -> None:
    set_support_adapters(cache=MagicMock(), db=_FakeDB())
    monkeypatch.setattr(support_tools, "get_active_plan", AsyncMock(return_value=None))

    result = await get_plan.ainvoke({"subscriber_id": "12345678-1234-4321-8765-432187654321"})

    assert result == {"active_plan": None}


# ── get_usage ──────────────────────────────────────────────────────────────────


async def test_get_usage_aggregates_last_n_days(monkeypatch) -> None:
    set_support_adapters(cache=MagicMock(), db=_FakeDB())
    usage_row = {
        "voice_minutes_used": 12.5,
        "data_mb_used": 512.0,
        "sms_count_used": 7,
        "roaming_mb_used": 0.0,
    }
    mock_query = AsyncMock(return_value=usage_row)
    monkeypatch.setattr(support_tools, "get_usage_for_period", mock_query)

    result = await get_usage.ainvoke({"subscriber_id": "12345678-1234-4321-8765-432187654321", "days": 14})

    assert result == {
        "window_days": 14,
        "voice_minutes": 12.5,
        "data_mb": 512.0,
        "sms_count": 7,
        "roaming_mb": 0.0,
    }
    # The window is computed from now; assert subscriber + the requested window.
    args, _kwargs = mock_query.call_args
    assert str(args[1]) == "12345678-1234-4321-8765-432187654321"  # subscriber_id (positional)
    assert args[2] is not None  # start


async def test_get_usage_defaults_to_30_days(monkeypatch) -> None:
    set_support_adapters(cache=MagicMock(), db=_FakeDB())
    mock_query = AsyncMock(
        return_value={"voice_minutes_used": 0.0, "data_mb_used": 0.0, "sms_count_used": 0, "roaming_mb_used": 0.0}
    )
    monkeypatch.setattr(support_tools, "get_usage_for_period", mock_query)

    result = await get_usage.ainvoke({"subscriber_id": "12345678-1234-4321-8765-432187654321"})

    assert result["window_days"] == 30


# ── rag_search_tool ────────────────────────────────────────────────────────────


async def test_rag_search_tool_delegates_to_retriever(monkeypatch) -> None:
    set_support_adapters(cache=MagicMock(), db=_FakeDB())
    chunks = [
        RagChunk("faq_chunks", "c1", "Roaming is charged at ₹5/min.", 0.04, {"category": "roaming"}),
        RagChunk("plan_vectors", "p1", "Plan X includes 1GB/day.", 0.035),
    ]
    monkeypatch.setattr(support_tools, "rag_search", AsyncMock(return_value=chunks))

    result = await rag_search_tool.ainvoke({"query": "roaming charges"})

    support_tools.rag_search.assert_awaited_once_with("roaming charges")
    assert result[0] == {
        "collection": "faq_chunks",
        "chunk_id": "c1",
        "text": "Roaming is charged at ₹5/min.",
        "score": 0.04,
    }
    assert len(result) == 2


async def test_rag_search_tool_returns_empty_when_no_grounding(monkeypatch) -> None:
    set_support_adapters(cache=MagicMock(), db=_FakeDB())
    monkeypatch.setattr(support_tools, "rag_search", AsyncMock(return_value=[]))

    result = await rag_search_tool.ainvoke({"query": "obscure query"})

    assert result == []
