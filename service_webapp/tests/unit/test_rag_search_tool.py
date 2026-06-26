"""Unit tests for the module-level ``rag_search`` LangGraph tool (Story 5.3; AC #6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.rag.retriever import RagChunk, rag_search, set_retriever


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure no retriever leaks between tests (the singleton is process-global)."""
    set_retriever(None)
    yield
    set_retriever(None)


async def test_rag_search_delegates_to_configured_singleton() -> None:
    expected = [RagChunk("faq_chunks", "c1", "text", 0.033, {"category": "billing"})]
    fake = MagicMock()
    fake.search = AsyncMock(return_value=expected)
    set_retriever(fake)

    result = await rag_search("what is my balance?")

    assert result == expected
    fake.search.assert_awaited_once_with("what is my balance?", top_k=3)


async def test_rag_search_forwards_top_k() -> None:
    fake = MagicMock()
    fake.search = AsyncMock(return_value=[])
    set_retriever(fake)

    await rag_search("query", top_k=5)

    fake.search.assert_awaited_once_with("query", top_k=5)


async def test_rag_search_returns_list_of_rag_chunks() -> None:
    fake = MagicMock()
    fake.search = AsyncMock(return_value=[RagChunk("plan_vectors", "p1", "plan text", 0.04)])
    set_retriever(fake)

    result = await rag_search("show plans")

    assert isinstance(result, list)
    assert all(isinstance(c, RagChunk) for c in result)


async def test_rag_search_returns_empty_when_not_initialised() -> None:
    set_retriever(None)
    result = await rag_search("anything")
    assert result == []
