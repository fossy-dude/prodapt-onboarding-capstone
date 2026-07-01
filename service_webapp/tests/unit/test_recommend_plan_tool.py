"""Tests for recommend_plan tool (Story 5.9 Task 8)."""

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from contextvars import Token

from agents.rag.retriever import RagChunk
from agents.support.tools import _run_recommend_plan


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
def mock_retriever(monkeypatch):
    """Patch _search_plans (as imported into tools.py) to return canned plan chunks."""
    calls = []

    async def fake_search_plans(query_text, top_k=10, filter_expr=None):
        calls.append({"query_text": query_text, "top_k": top_k, "filter_expr": filter_expr})
        return [
            RagChunk(
                collection="plan_vectors",
                chunk_id="plan-1",
                text="Premium Plan 50GB data unlimited calls unlimited SMS ₹299",
                score=0.95,
                metadata={
                    "plan_id": "plan-1",
                    "price": 29900,
                    "data_limit_mb": 51200,
                    "voice_minutes": 0,
                    "sms_count": 0,
                    "usage_category": "DATA_HEAVY",
                },
            ),
            RagChunk(
                collection="plan_vectors",
                chunk_id="plan-2",
                text="Standard Plan 30GB data 500min 100SMS ₹199",
                score=0.85,
                metadata={
                    "plan_id": "plan-2",
                    "price": 19900,
                    "data_limit_mb": 30720,
                    "voice_minutes": 500,
                    "sms_count": 100,
                    "usage_category": "BALANCED",
                },
            ),
            RagChunk(
                collection="plan_vectors",
                chunk_id="plan-3",
                text="Value Plan 10GB data 200min 50SMS ₹99",
                score=0.75,
                metadata={
                    "plan_id": "plan-3",
                    "price": 9900,
                    "data_limit_mb": 10240,
                    "voice_minutes": 200,
                    "sms_count": 50,
                    "usage_category": "VALUE",
                },
            ),
        ]

    import agents.support.tools as tools_module

    monkeypatch.setattr(tools_module, "_search_plans", fake_search_plans)
    return calls


@pytest.fixture
def mock_identity(monkeypatch):
    """Mock identity context variable."""
    import agents.support.identity as identity_module

    test_uuid = str(uuid.uuid4())
    token: Token = identity_module._subscriber_id.set(test_uuid)
    yield test_uuid
    identity_module._subscriber_id.reset(token)


@pytest.fixture
def stub_profile_and_plan(monkeypatch):
    """Stub the DB helper functions recommend_plan calls, with sane defaults."""
    import agents.support.tools as tools_module

    async def mock_get_profile(conn, subscriber_id, days=30):
        return {
            "total_data_mb": 5000,
            "total_voice_seconds": 6000,
            "total_intl_seconds": 300,
            "total_sms_count": 100,
            "total_spend_paise": 10000,
        }

    async def mock_get_current(conn, subscriber_id):
        return None

    monkeypatch.setattr(tools_module, "get_subscriber_usage_profile", mock_get_profile)
    monkeypatch.setattr(tools_module, "get_current_plan_details", mock_get_current)
    return tools_module


@pytest.mark.asyncio
async def test_recommend_plan_with_data_preference_returns_up_to_three_plans(
    mock_db, mock_retriever, mock_identity, stub_profile_and_plan, monkeypatch
):
    monkeypatch.setattr(stub_profile_and_plan, "_require_db", lambda: mock_db)

    result = await _run_recommend_plan(data_preference="more", voice_preference=None, sms_preference=None)

    assert "plans" in result
    assert len(result["plans"]) == 3
    assert mock_retriever[0]["filter_expr"] == "data_limit_mb > 5000"


@pytest.mark.asyncio
async def test_recommend_plan_combines_multiple_axes_into_one_filter(
    mock_db, mock_retriever, mock_identity, stub_profile_and_plan, monkeypatch
):
    monkeypatch.setattr(stub_profile_and_plan, "_require_db", lambda: mock_db)

    await _run_recommend_plan(data_preference="more", voice_preference="less", sms_preference=None)

    assert mock_retriever[0]["filter_expr"] == "data_limit_mb > 5000 and voice_minutes < 100"


@pytest.mark.asyncio
async def test_recommend_plan_no_preference_needs_clarification(mock_db, mock_identity, monkeypatch):
    import agents.support.tools as tools_module

    monkeypatch.setattr(tools_module, "_require_db", lambda: mock_db)

    result = await _run_recommend_plan(data_preference=None, voice_preference=None, sms_preference=None)

    assert result.get("needs_clarification") is True
    assert "question" in result


@pytest.mark.asyncio
async def test_recommend_plan_falls_back_when_filter_yields_nothing(
    mock_db, mock_identity, stub_profile_and_plan, monkeypatch
):
    """If the filtered search comes back empty, retry unfiltered instead of returning nothing."""
    import agents.support.tools as tools_module

    monkeypatch.setattr(stub_profile_and_plan, "_require_db", lambda: mock_db)

    calls = []

    async def fake_search_plans(query_text, top_k=10, filter_expr=None):
        calls.append(filter_expr)
        if filter_expr is not None:
            return []
        return [
            RagChunk(
                collection="plan_vectors",
                chunk_id="plan-1",
                text="Premium Plan 50GB data ₹299",
                score=0.95,
                metadata={
                    "plan_id": "plan-1",
                    "price": 29900,
                    "data_limit_mb": 51200,
                    "voice_minutes": 0,
                    "sms_count": 0,
                },
            )
        ]

    monkeypatch.setattr(tools_module, "_search_plans", fake_search_plans)

    result = await _run_recommend_plan(data_preference="more", voice_preference=None, sms_preference=None)

    assert calls == ["data_limit_mb > 5000", None]
    assert len(result["plans"]) == 1


@pytest.mark.asyncio
async def test_recommend_plan_invalid_direction_treated_as_no_preference(mock_db, mock_identity, monkeypatch):
    import agents.support.tools as tools_module

    monkeypatch.setattr(tools_module, "_require_db", lambda: mock_db)

    result = await _run_recommend_plan(data_preference="banana", voice_preference=None, sms_preference=None)

    assert result.get("needs_clarification") is True
