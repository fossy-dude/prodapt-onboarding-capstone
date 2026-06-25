"""Tests for feedback endpoint (Story 5.9 Task 8)."""

import uuid

import pytest

from db.support.commands import log_recommendation_feedback


@pytest.mark.asyncio
async def test_log_recommendation_feedback_accepted():
    """Test logging ACCEPTED recommendation feedback."""
    executed = []

    class MockConnection:
        async def execute(self, sql, params=None):
            executed.append((sql, params))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    await log_recommendation_feedback(
        MockConnection(),
        subscriber_id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        action="ACCEPTED",
    )

    assert len(executed) == 1
    sql, params = executed[0]
    assert "INSERT INTO segmentation_recommendation_feedback" in sql
    assert params[2] == "ACCEPTED"
    # recommendation_type is hardcoded in SQL, not a parameter
    assert "PLAN_RECOMMENDATION" in sql


@pytest.mark.asyncio
async def test_log_recommendation_feedback_dismissed():
    """Test logging DISMISSED recommendation feedback."""
    executed = []

    class MockConnection:
        async def execute(self, sql, params=None):
            executed.append((sql, params))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    await log_recommendation_feedback(
        MockConnection(),
        subscriber_id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        action="DISMISSED",
    )

    assert len(executed) == 1
    sql, params = executed[0]
    assert "INSERT INTO segmentation_recommendation_feedback" in sql
    assert params[2] == "DISMISSED"
    # recommendation_type is hardcoded in SQL, not a parameter
    assert "PLAN_RECOMMENDATION" in sql


@pytest.mark.asyncio
async def test_feedback_request_validation():
    """Test FeedbackRequest model validation."""
    from routers.support import FeedbackRequest

    # Valid ACCEPTED request
    payload = FeedbackRequest(
        subscriber_id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        action="ACCEPTED",
    )
    assert payload.action == "ACCEPTED"

    # Valid DISMISSED request
    payload = FeedbackRequest(
        subscriber_id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        action="DISMISSED",
    )
    assert payload.action == "DISMISSED"

    # Invalid action should raise validation error
    with pytest.raises(ValueError, match="Invalid action"):
        FeedbackRequest(
            subscriber_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            action="INVALID",
        )
