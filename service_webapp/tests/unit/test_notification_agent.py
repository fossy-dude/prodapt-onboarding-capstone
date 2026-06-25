"""Unit tests for Notification Agent (Story 5.10 Task 6)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from agents.notification.graph import (
    NotificationAgentState,
    create_notification_graph,
    decide_notification,
    publish_notification,
)


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a decision."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "should_send": True,
                    "type": "RECHARGE_REMINDER",
                    "channel": "push",
                    "delay_hours": 1,
                }
            )
        )
    )
    return llm


@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer."""
    producer = MagicMock()
    producer.send = AsyncMock()
    return producer


@pytest.mark.asyncio
async def test_decide_notification_with_send():
    """Test decide_notification when should_send=true."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "User asked about balance"}',
        "subscriber_id": str(uuid4()),
        "should_send": None,
        "notification_type": None,
        "channel": None,
        "delay_hours": None,
        "trace_id": "test_trace_id",
    }

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "should_send": True,
                    "type": "RECHARGE_REMINDER",
                    "channel": "push",
                    "delay_hours": 1,
                }
            )
        )
    )

    with patch("langchain_openai.ChatOpenAI", return_value=mock_llm):
        result = await decide_notification(state)

    assert result["should_send"] is True
    assert result["notification_type"] == "RECHARGE_REMINDER"
    assert result["channel"] == "push"
    assert result["delay_hours"] == 1


@pytest.mark.asyncio
async def test_decide_notification_without_send():
    """Test decide_notification when should_send=false."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "General inquiry"}',
        "subscriber_id": str(uuid4()),
        "should_send": None,
        "notification_type": None,
        "channel": None,
        "delay_hours": None,
        "trace_id": "test_trace_id",
    }

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "should_send": False,
                    "type": "NONE",
                    "channel": "push",
                    "delay_hours": 0,
                }
            )
        )
    )

    with patch("langchain_openai.ChatOpenAI", return_value=mock_llm):
        result = await decide_notification(state)

    assert result["should_send"] is False
    assert result["notification_type"] == "NONE"


@pytest.mark.asyncio
async def test_decide_notification_invalid_json():
    """Test decide_notification handles invalid JSON gracefully."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "test"}',
        "subscriber_id": str(uuid4()),
        "should_send": None,
        "notification_type": None,
        "channel": None,
        "delay_hours": None,
        "trace_id": "test_trace_id",
    }

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="invalid json"))

    with patch("langchain_openai.ChatOpenAI", return_value=mock_llm):
        result = await decide_notification(state)

    # Should default to safe values
    assert result["should_send"] is False
    assert result["notification_type"] == "NONE"


@pytest.mark.asyncio
async def test_publish_notification_with_send(mock_kafka_producer):
    """Test publish_notification calls KafkaProducer when should_send=True."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "User asked about recharge"}',
        "subscriber_id": str(uuid4()),
        "should_send": True,
        "notification_type": "RECHARGE_REMINDER",
        "channel": "push",
        "delay_hours": 1,
        "trace_id": "test_trace_id",
    }

    # Create a mock producer object
    mock_producer_obj = MagicMock()
    mock_producer_obj.producer = mock_kafka_producer

    with patch("agents.notification.graph._kafka_producer", mock_producer_obj):
        result = await publish_notification(state)

    # Verify Kafka producer was called
    mock_kafka_producer.send.assert_called_once()
    call_args = mock_kafka_producer.send.call_args
    assert call_args[0][0] == "notification.events"
    assert call_args[1]["key"] == state["subscriber_id"].encode()

    # Verify payload structure
    import json

    from models.envelope import EventEnvelope

    envelope_bytes = call_args[1]["value"]
    envelope = EventEnvelope.model_validate_json(envelope_bytes)
    assert envelope.event_type == "notification.session_end"
    assert envelope.payload["type"] == "RECHARGE_REMINDER"
    assert envelope.payload["subscriber_id"] == state["subscriber_id"]
    assert envelope.payload["channel"] == "push"
    assert envelope.payload["delay_hours"] == 1
    # Summary truncated for PII safety
    assert len(envelope.payload["session_summary"]) <= 200


@pytest.mark.asyncio
async def test_publish_notification_without_send():
    """Test publish_notification skips Kafka when should_send=False."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "General inquiry"}',
        "subscriber_id": str(uuid4()),
        "should_send": False,
        "notification_type": "NONE",
        "channel": "push",
        "delay_hours": 0,
        "trace_id": "test_trace_id",
    }

    mock_producer = MagicMock()
    mock_producer_obj = MagicMock()
    mock_producer_obj.producer = mock_producer

    with patch("agents.notification.graph._kafka_producer", mock_producer_obj):
        result = await publish_notification(state)

    # Should log warning and not call Kafka
    mock_producer.send.assert_not_called()


@pytest.mark.asyncio
async def test_publish_notification_no_producer():
    """Test publish_notification handles missing producer gracefully."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "test"}',
        "subscriber_id": str(uuid4()),
        "should_send": True,
        "notification_type": "RECHARGE_REMINDER",
        "channel": "push",
        "delay_hours": 1,
        "trace_id": "test_trace_id",
    }

    with patch("agents.notification.graph._kafka_producer", None):
        result = await publish_notification(state)

    # Should return state unchanged
    assert result == state


@pytest.mark.asyncio
async def test_notification_graph_full_flow_with_send():
    """Test full graph flow when notification should be sent."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "User asked about recharge"}',
        "subscriber_id": str(uuid4()),
        "should_send": None,
        "notification_type": None,
        "channel": None,
        "delay_hours": None,
        "trace_id": "test_trace_id",
    }

    # Mock LLM to return should_send=True
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "should_send": True,
                    "type": "RECHARGE_REMINDER",
                    "channel": "push",
                    "delay_hours": 1,
                }
            )
        )
    )

    # Mock Kafka producer
    mock_producer = MagicMock()
    mock_producer.send = AsyncMock()
    mock_producer_obj = MagicMock()
    mock_producer_obj.producer = mock_producer

    with (
        patch("langchain_openai.ChatOpenAI", return_value=mock_llm),
        patch("agents.notification.graph._kafka_producer", mock_producer_obj),
    ):
        graph = create_notification_graph()
        result = await graph.ainvoke(state)

    # Verify decision made and Kafka called
    assert result["should_send"] is True
    assert result["notification_type"] == "RECHARGE_REMINDER"
    mock_producer.send.assert_called_once()


@pytest.mark.asyncio
async def test_notification_graph_full_flow_without_send():
    """Test full graph flow when notification should NOT be sent."""
    state: NotificationAgentState = {
        "session_summary": '{"summary_text": "General inquiry"}',
        "subscriber_id": str(uuid4()),
        "should_send": None,
        "notification_type": None,
        "channel": None,
        "delay_hours": None,
        "trace_id": "test_trace_id",
    }

    # Mock LLM to return should_send=False
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "should_send": False,
                    "type": "NONE",
                    "channel": "push",
                    "delay_hours": 0,
                }
            )
        )
    )

    with patch("langchain_openai.ChatOpenAI", return_value=mock_llm):
        graph = create_notification_graph()
        result = await graph.ainvoke(state)

    # Verify decision made but no Kafka call
    assert result["should_send"] is False
    assert result["notification_type"] == "NONE"


__all__ = [
    "test_notification_agent",
]
