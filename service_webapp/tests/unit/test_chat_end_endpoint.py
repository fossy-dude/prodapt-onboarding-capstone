"""Unit tests for POST /api/v1/support/chat/end endpoint (Story 5.10 Task 6)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.support import router as support_router


@pytest.fixture
def app():
    """Create a test FastAPI app with the support router."""
    app = FastAPI()
    app.include_router(support_router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_jwt_payload():
    """Mock JWT payload for authenticated subscriber."""
    return {
        "sub": str(uuid4()),
        "cognito:groups": ["subscribers"],
    }


@pytest.fixture
def mock_conclusion_graph():
    """Mock Conclusion Agent graph."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    return graph


def test_post_chat_end_returns_202(client, mock_jwt_payload, mock_conclusion_graph):
    """Test POST /api/v1/support/chat/end returns 202 Accepted."""
    session_id = str(uuid4())

    with (
        patch("routers.support.require_role", return_value=mock_jwt_payload),
        patch("routers.support.get_conclusion_graph", return_value=mock_conclusion_graph),
    ):
        response = client.post(
            "/api/v1/support/chat/end",
            json={"session_id": session_id},
            headers={"Authorization": "Bearer fake_token"},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["data"]["status"] == "accepted"


def test_post_chat_end_fires_conclusion_agent(client, mock_jwt_payload, mock_conclusion_graph):
    """Test POST /api/v1/support/chat/end fires Conclusion Agent as background task."""
    session_id = str(uuid4())
    subscriber_id = mock_jwt_payload["sub"]

    with (
        patch("routers.support.require_role", return_value=mock_jwt_payload),
        patch("routers.support.get_conclusion_graph", return_value=mock_conclusion_graph),
        patch("asyncio.create_task") as mock_create_task,
    ):
        response = client.post(
            "/api/v1/support/chat/end",
            json={"session_id": session_id},
            headers={"Authorization": "Bearer fake_token"},
        )

        assert response.status_code == 202
        # Verify asyncio.create_task was called
        mock_create_task.assert_called_once()

        # Verify the task was created with the correct invocation
        task_arg = mock_create_task.call_args[0][0]
        assert isinstance(task_arg, asyncio.coroutines.Coroutine)


def test_post_chat_end_passes_correct_state_to_agent(client, mock_jwt_payload, mock_conclusion_graph):
    """Test POST /api/v1/support/chat/end passes correct state to Conclusion Agent."""
    session_id = str(uuid4())
    subscriber_id = mock_jwt_payload["sub"]

    # Track the invocation
    invoked_states = []

    async def mock_ainvoke(state):
        invoked_states.append(state)
        return state

    mock_conclusion_graph.ainvoke = mock_ainvoke

    with (
        patch("routers.support.require_role", return_value=mock_jwt_payload),
        patch("routers.support.get_conclusion_graph", return_value=mock_conclusion_graph),
        patch("asyncio.create_task", side_effect=lambda coro: asyncio.create_task(coro)),
    ):
        response = client.post(
            "/api/v1/support/chat/end",
            json={"session_id": session_id},
            headers={"Authorization": "Bearer fake_token"},
        )

        assert response.status_code == 202

        # Wait for the background task to complete
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))

        # Verify the state passed to the agent
        assert len(invoked_states) == 1
        state = invoked_states[0]
        assert state["session_id"] == session_id
        assert state["subscriber_id"] == subscriber_id
        assert state["trace_id"] != "unknown"  # Should have a trace_id


def test_post_chat_end_returns_503_when_graph_not_initialized(client, mock_jwt_payload):
    """Test POST /api/v1/support/chat/end returns 503 when graph not initialized."""
    session_id = str(uuid4())

    with (
        patch("routers.support.require_role", return_value=mock_jwt_payload),
        patch("routers.support.get_conclusion_graph", return_value=None),
    ):
        response = client.post(
            "/api/v1/support/chat/end",
            json={"session_id": session_id},
            headers={"Authorization": "Bearer fake_token"},
        )

        assert response.status_code == 503
    data = response.json()
    assert data["error"]["code"] == "NOT_READY"


def test_post_chat_end_requires_authentication(client):
    """Test POST /api/v1/support/chat/end requires authentication."""
    session_id = str(uuid4())

    response = client.post(
        "/api/v1/support/chat/end",
        json={"session_id": session_id},
    )

    assert response.status_code == 401


__all__ = [
    "test_chat_end_endpoint",
]
