"""Unit tests for Conclusion Agent (Story 5.10 Task 6)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from agents.conclusion.graph import (
    ConclusionAgentState,
    create_conclusion_graph,
    load_session_history,
    store_learning,
    summarise_session,
    trigger_notification,
)


@pytest.fixture
def mock_valkey():
    """Mock Valkey client with chat_context data."""
    client = MagicMock()
    client.hgetall = AsyncMock(
        return_value={
            "turn_0": json.dumps(
                {
                    "role": "user",
                    "content": "What's my balance?",
                    "timestamp": 1000,
                }
            ),
            "turn_1": json.dumps(
                {
                    "role": "assistant",
                    "content": "Your balance is ₹50",
                    "timestamp": 1001,
                }
            ),
            "turn_2": json.dumps(
                {
                    "role": "user",
                    "content": "Thanks",
                    "timestamp": 1002,
                }
            ),
        }
    )
    return client


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a JSON summary."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "summary_text": "User asked about balance, thanked assistant",
                    "topics": ["balance inquiry"],
                    "actions": [],
                    "unresolved": [],
                }
            )
        )
    )
    return llm


@pytest.fixture
def mock_db():
    """Mock database adapter."""
    db = MagicMock()
    conn = MagicMock()
    conn.execute = AsyncMock()
    db.transaction = MagicMock()
    db.transaction.return_value.__aenter__ = AsyncMock(return_value=conn)
    db.transaction.return_value.__aexit__ = AsyncMock()
    return db


@pytest.fixture
def mock_notification_graph():
    """Mock Notification Agent graph."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    return graph


@pytest.mark.asyncio
async def test_load_session_history(mock_valkey):
    """Test load_session_history reads all turns correctly."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": None,
        "trace_id": "0" * 32,
    }

    with patch("agents.conclusion.graph.get_valkey_client", return_value=mock_valkey):
        result = await load_session_history(state)

    assert len(result["session_history"]) == 3
    assert result["session_history"][0]["role"] == "user"
    assert result["session_history"][0]["content"] == "What's my balance?"
    assert result["session_history"][1]["role"] == "assistant"
    assert result["session_history"][2]["role"] == "user"


@pytest.mark.asyncio
async def test_load_session_history_expired_key():
    """Test load_session_history handles expired keys gracefully."""
    client = MagicMock()
    client.hgetall = AsyncMock(return_value={})

    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": None,
        "trace_id": "0" * 32,
    }

    with patch("agents.conclusion.graph.get_valkey_client", return_value=client):
        result = await load_session_history(state)

    assert result["session_history"] == []


@pytest.mark.asyncio
async def test_summarise_session(mock_llm):
    """Test summarise_session calls LLM with formatted history."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [
            {"role": "user", "content": "Hello", "timestamp": 1000},
            {"role": "assistant", "content": "Hi there", "timestamp": 1001},
        ],
        "summary": None,
        "trace_id": "test_trace_id",
    }

    with patch("langchain_openai.ChatOpenAI", return_value=mock_llm):
        result = await summarise_session(state)

    assert result["summary"] is not None
    summary_data = json.loads(result["summary"])
    assert "summary_text" in summary_data
    assert "topics" in summary_data
    assert "actions" in summary_data
    assert "unresolved" in summary_data


@pytest.mark.asyncio
async def test_store_learning(mock_db):
    """Test store_learning INSERT called with correct session_id + summary."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": '{"summary_text": "test"}',
        "trace_id": "0" * 32,
    }

    with patch("agents.conclusion.graph.get_db_adapter", return_value=mock_db):
        result = await store_learning(state)

    # Verify DB was called
    mock_db.transaction.__aenter__.assert_called_once()
    conn = mock_db.transaction.return_value.__aenter__.return_value
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    assert "support_session_learnings" in call_args[0][0]
    assert state["session_id"] in call_args[0][1]
    assert state["summary"] in call_args[0][1]


@pytest.mark.asyncio
async def test_store_learning_no_db():
    """Test store_learning handles missing DB gracefully."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": '{"summary_text": "test"}',
        "trace_id": "0" * 32,
    }

    with patch("agents.conclusion.graph.get_db_adapter", return_value=None):
        result = await store_learning(state)

    # Should return state unchanged
    assert result == state


@pytest.mark.asyncio
async def test_trigger_notification(mock_notification_graph):
    """Test trigger_notification calls notification_graph.ainvoke."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": '{"summary_text": "test"}',
        "trace_id": "test_trace_id",
    }

    with patch("agents.conclusion.graph.get_notification_graph", return_value=mock_notification_graph):
        result = await trigger_notification(state)

    # Verify notification was invoked
    mock_notification_graph.ainvoke.assert_called_once()
    call_args = mock_notification_graph.ainvoke.call_args
    assert call_args[1]["session_summary"] == state["summary"]
    assert call_args[1]["subscriber_id"] == state["subscriber_id"]
    assert call_args[1]["trace_id"] == state["trace_id"]


@pytest.mark.asyncio
async def test_trigger_notification_no_graph():
    """Test trigger_notification handles missing graph gracefully."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": '{"summary_text": "test"}',
        "trace_id": "0" * 32,
    }

    with patch("agents.conclusion.graph.get_notification_graph", return_value=None):
        result = await trigger_notification(state)

    # Should return state unchanged
    assert result == state


@pytest.mark.asyncio
async def test_conclusion_graph_integration():
    """Test full graph execution with all nodes mocked."""
    state: ConclusionAgentState = {
        "session_id": str(uuid4()),
        "subscriber_id": str(uuid4()),
        "session_history": [],
        "summary": None,
        "trace_id": "test_trace_id",
    }

    # Mock all dependencies
    mock_valkey = MagicMock()
    mock_valkey.hgetall = AsyncMock(return_value={})

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content='{"summary_text": "test"}'))

    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_db.transaction = MagicMock()
    mock_db.transaction.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_db.transaction.return_value.__aexit__ = AsyncMock()

    mock_notification = MagicMock()
    mock_notification.ainvoke = AsyncMock()

    with (
        patch("agents.conclusion.graph.get_valkey_client", return_value=mock_valkey),
        patch("langchain_openai.ChatOpenAI", return_value=mock_llm),
        patch("agents.conclusion.graph.get_db_adapter", return_value=mock_db),
        patch("agents.conclusion.graph.get_notification_graph", return_value=mock_notification),
    ):
        graph = create_conclusion_graph()
        result = await graph.ainvoke(state)

    # Verify all nodes executed
    assert result["session_history"] == []  # Loaded from empty Valkey
    assert result["summary"] is not None  # Generated by LLM
    mock_conn.execute.assert_called_once()  # DB insert
    mock_notification.ainvoke.assert_called_once()  # Notification triggered


__all__ = [
    "test_conclusion_agent",
]
