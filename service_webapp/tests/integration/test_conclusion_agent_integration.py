"""Integration tests for Conclusion Agent (Story 5.10 Task 6).

These tests use real Postgres and Valkey via testcontainers (@pytest.mark.slow).
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from core.adapters.postgres import Psycopg3AsyncAdapter
from core.adapters.redis import ValkeyAdapter
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from agents.conclusion.graph import create_conclusion_graph
from db.support.queries import get_session_learning


@pytest.fixture(scope="module")
def postgres_container():
    """Spawn a Postgres test container."""
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest.fixture(scope="module")
def valkey_container():
    """Spawn a Redis/Valkey test container."""
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="module")
async def db_adapter(postgres_container):
    """Create a real Postgres adapter for testing."""
    conn_str = postgres_container.get_connection_url()
    adapter = Psycopg3AsyncAdapter(conninfo_from=conn_str)
    await adapter.start()
    yield adapter
    await adapter.close()


@pytest.fixture(scope="module")
async def cache_adapter(valkey_container):
    """Create a real Valkey adapter for testing."""
    url = valkey_container.get_connection_url()
    adapter = ValkeyAdapter(url)
    await adapter.start()
    yield adapter
    await adapter.close()


@pytest.fixture(scope="module")
async def setup_schema(db_adapter):
    """Set up the support_session_learnings table."""
    async with db_adapter.pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_session_learnings (
                id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                session_id UUID NOT NULL,
                learning_type VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
            );
        """)
    yield
    # Cleanup
    async with db_adapter.pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS support_session_learnings")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_conclusion_agent_integration(db_adapter, cache_adapter, setup_schema):
    """Integration test: Store turns → fire conclusion agent → verify DB insert.

    This test creates real chat turns in Valkey, invokes the Conclusion Agent,
    and verifies that a row was inserted into support_session_learnings.
    """
    session_id = str(uuid4())
    subscriber_id = str(uuid4())

    # Store chat turns in Valkey
    turns = [
        {"role": "user", "content": "What's my balance?", "timestamp": 1000},
        {"role": "assistant", "content": "Your balance is ₹50", "timestamp": 1001},
        {"role": "user", "content": "Thanks", "timestamp": 1002},
    ]

    key = f"chat_context:{session_id}"
    for i, turn in enumerate(turns):
        await cache_adapter.client.hset(key, f"turn_{i}", json.dumps(turn))

    # Wire adapters (simulate FastAPI startup)
    from agents.support.tools import set_support_adapters

    set_support_adapters(cache_adapter, db_adapter)

    # Mock LLM to avoid API calls
    mock_summary = json.dumps(
        {
            "summary_text": "User asked about balance, thanked assistant",
            "topics": ["balance inquiry"],
            "actions": [],
            "unresolved": [],
        }
    )

    from unittest.mock import AsyncMock, MagicMock, patch

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=mock_summary))

    # Mock Notification Agent to avoid A2A complexity
    mock_notification = MagicMock()
    mock_notification.ainvoke = AsyncMock()

    with (
        patch("langchain_openai.ChatOpenAI", return_value=mock_llm),
        patch("agents.conclusion.graph.get_notification_graph", return_value=mock_notification),
    ):
        # Create and invoke the graph
        graph = create_conclusion_graph()
        state = {
            "session_id": session_id,
            "subscriber_id": subscriber_id,
            "session_history": [],
            "summary": None,
            "trace_id": "0" * 32,
        }

        result = await graph.ainvoke(state)

    # Verify LLM was called
    assert mock_llm.ainvoke.called
    assert result["summary"] == mock_summary

    # Verify DB insert (wait briefly for async operation)
    await asyncio.sleep(0.2)

    async with db_adapter.pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM support_session_learnings WHERE session_id = %s", (session_id,))
        row = await cur.fetchone()

    assert row is not None
    assert row[1] == session_id  # session_id
    assert row[2] == "session_summary"  # learning_type
    assert row[3] == mock_summary  # content

    # Cleanup Valkey
    await cache_adapter.client.delete(key)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_conclusion_agent_empty_history(db_adapter, cache_adapter, setup_schema):
    """Integration test: Empty session history (expired key)."""
    session_id = str(uuid4())
    subscriber_id = str(uuid4())

    # Wire adapters
    from agents.support.tools import set_support_adapters

    set_support_adapters(cache_adapter, db_adapter)

    # Mock LLM
    mock_summary = json.dumps(
        {
            "summary_text": "No history available",
            "topics": [],
            "actions": [],
            "unresolved": [],
        }
    )

    from unittest.mock import AsyncMock, MagicMock, patch

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=mock_summary))

    mock_notification = MagicMock()
    mock_notification.ainvoke = AsyncMock()

    with (
        patch("langchain_openai.ChatOpenAI", return_value=mock_llm),
        patch("agents.conclusion.graph.get_notification_graph", return_value=mock_notification),
    ):
        graph = create_conclusion_graph()
        state = {
            "session_id": session_id,
            "subscriber_id": subscriber_id,
            "session_history": [],
            "summary": None,
            "trace_id": "0" * 32,
        }

        result = await graph.ainvoke(state)

    # Should still work with empty history
    assert result["summary"] == mock_summary
    assert result["session_history"] == []


__all__ = [
    "test_conclusion_agent_integration",
]
