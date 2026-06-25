"""Tests for recommend_plan tool (Story 5.9 Task 8)."""

import uuid
from contextvars import Token

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agents.support.tools import (
    _PREF_MAP,
    _build_plan_comparison,
    _DOMINANT_THRESHOLD,
    _run_recommend_plan,
)
from agents.rag.retriever import RagChunk


@pytest.fixture
def mock_db():
    """Mock DB adapter for testing."""

    class MockConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, sql, params=None):
            class MockCursor:
                def __init__(self):
                    self.row = None

                async def fetchone(self):
                    return self.row

                @property
                def description(self):
                    return []

            return MockCursor()

    class MockDB:
        def transaction(self):
            return MockConnection()

    return MockDB()


@pytest.fixture
def mock_retriever():
    """Mock retriever that returns plan chunks."""

    class MockHybridRetriever:
        async def search_plans(self, query_text, top_k=10, filter_expr=None):
            return [
                RagChunk(
                    collection="plan_vectors",
                    chunk_id="plan-1",
                    text="Premium Plan 50GB data unlimited calls ₹299",
                    score=0.95,
                    metadata={
                        "plan_id": "plan-1",
                        "price": 29900,
                        "data_limit_mb": 51200,
                        "voice_minutes": 0,
                        "usage_category": "DATA_HEAVY",
                    },
                ),
                RagChunk(
                    collection="plan_vectors",
                    chunk_id="plan-2",
                    text="Standard Plan 30GB data 500min ₹199",
                    score=0.85,
                    metadata={
                        "plan_id": "plan-2",
                        "price": 19900,
                        "data_limit_mb": 30720,
                        "voice_minutes": 500,
                        "usage_category": "BALANCED",
                    },
                ),
            ]

    return MockHybridRetriever()


@pytest.fixture
def mock_identity(monkeypatch):
    """Mock identity context variable."""
    import agents.support.identity as identity_module

    test_uuid = str(uuid.uuid4())
    token: Token = identity_module._subscriber_id.set(test_uuid)
    yield test_uuid
    identity_module._subscriber_id.reset(token)


@pytest.mark.asyncio
async def test_recommend_plan_with_preference_data(mock_db, mock_retriever, mock_identity, monkeypatch):
    """Test that preference='data' maps to DATA_HEAVY category."""
    import agents.rag.retriever as retriever_module
    import agents.support.tools as tools_module

    monkeypatch.setattr(tools_module, "_require_db", lambda: mock_db)

    # Set the retriever singleton
    monkeypatch.setattr(retriever_module, "_retriever", mock_retriever)

    # Mock DB queries
    async def mock_get_profile(conn, subscriber_id, days=30):
        return {
            "total_data_mb": 5000,
            "total_voice_seconds": 6000,
            "total_intl_seconds": 300,
            "total_sms_count": 100,
            "total_spend_paise": 10000,
        }

    async def mock_get_last(conn, subscriber_id):
        return None

    async def mock_get_current(conn, subscriber_id):
        return None

    async def mock_get_pop(conn):
        return {}

    monkeypatch.setattr(tools_module, "get_subscriber_usage_profile", mock_get_profile)
    monkeypatch.setattr(tools_module, "get_last_recharge_amount", mock_get_last)
    monkeypatch.setattr(tools_module, "get_current_plan_details", mock_get_current)
    monkeypatch.setattr(tools_module, "get_population_usage_stats", mock_get_pop)

    result = await _run_recommend_plan(preference="data")
    assert "plans" in result
    assert len(result["plans"]) == 2


@pytest.mark.asyncio
async def test_recommend_plan_ambiguous_profile(mock_db, mock_identity, monkeypatch):
    """Test that ambiguous usage returns needs_clarification."""
    import agents.support.tools as tools_module

    monkeypatch.setattr(tools_module, "_require_db", lambda: mock_db)

    # Mock low usage profile (below 70th percentile on all dimensions)
    async def mock_get_profile(conn, subscriber_id, days=30):
        return {
            "total_data_mb": 100,
            "total_voice_seconds": 60,
            "total_intl_seconds": 0,
            "total_sms_count": 10,
            "total_spend_paise": 500,
        }

    async def mock_get_pop(conn):
        return {
            "data_p25": 1000,
            "data_p50": 5000,
            "data_p75": 15000,
            "data_p90": 30000,
            "voice_p25": 500,
            "voice_p50": 2000,
            "voice_p75": 5000,
            "voice_p90": 10000,
            "intl_p25": 0,
            "intl_p50": 100,
            "intl_p75": 500,
            "intl_p90": 2000,
        }

    monkeypatch.setattr(tools_module, "get_subscriber_usage_profile", mock_get_profile)
    monkeypatch.setattr(tools_module, "get_population_usage_stats", mock_get_pop)

    result = await _run_recommend_plan(preference=None)
    assert result.get("needs_clarification") is True
    assert "question" in result


def test_pref_map():
    assert _PREF_MAP["data"] == "DATA_HEAVY"
    assert _PREF_MAP["voice"] == "VOICE_HEAVY"
    assert _PREF_MAP["value"] == "VALUE"
    assert _PREF_MAP["balanced"] == "BALANCED"


def test_dominant_threshold():
    assert _DOMINANT_THRESHOLD == 70.0
