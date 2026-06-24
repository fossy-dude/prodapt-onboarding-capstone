"""Unit tests for notifications DB layer (Story 4.2 Task 2).

Tests DB functions:
- get_preferences(db, subscriber_id) -> list of dict
- upsert_preference(db, subscriber_id, notification_type, is_enabled) -> None
- insert_notification_event(db, subscriber_id, notification_type, channel, payload, trace_id) -> None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from db.notifications.commands import insert_notification_event, upsert_preference
from db.notifications.queries import get_preferences


class TestGetPreferences:
    """Test get_preferences function."""

    @pytest.mark.asyncio
    async def test_get_preferences_returns_empty_list_when_no_rows(self):
        """Should return empty list when subscriber has no preferences."""
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchall=AsyncMock(return_value=[])))

        result = await get_preferences(db, str(uuid4()))

        assert result == []
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_preferences_returns_existing_preferences(self):
        """Should return list of existing preferences."""
        subscriber_id = str(uuid4())
        expected_rows = [
            {"notification_type": "LOW_BALANCE", "is_enabled": True},
            {"notification_type": "BALANCE_DEPLETED", "is_enabled": False},
        ]

        db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=expected_rows)
        db.execute = AsyncMock(return_value=mock_cursor)

        result = await get_preferences(db, subscriber_id)

        assert len(result) == 2
        assert result[0]["notification_type"] == "LOW_BALANCE"
        assert result[0]["is_enabled"] is True
        assert result[1]["notification_type"] == "BALANCE_DEPLETED"
        assert result[1]["is_enabled"] is False


class TestUpsertPreference:
    """Test upsert_preference function."""

    @pytest.mark.asyncio
    async def test_upsert_preference_inserts_new_preference(self):
        """Should insert new preference when none exists."""
        subscriber_id = str(uuid4())
        db = MagicMock()
        db.execute = AsyncMock()

        await upsert_preference(db, subscriber_id, "LOW_BALANCE", True, "push")

        db.execute.assert_called_once()
        call_args = db.execute.call_args
        sql = call_args[0][0]
        # Remove whitespace for flexible matching
        assert "INSERT INTO notifications_preferences" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE SET" in sql
        assert "is_enabled = EXCLUDED.is_enabled" in sql

    @pytest.mark.asyncio
    async def test_upsert_preference_updates_existing_preference(self):
        """Should update existing preference when one exists."""
        subscriber_id = str(uuid4())
        db = MagicMock()
        db.execute = AsyncMock()

        await upsert_preference(db, subscriber_id, "LOW_BALANCE", False, "push")

        db.execute.assert_called_once()
        call_args = db.execute.call_args
        assert "INSERT INTO notifications_preferences" in call_args[0][0]
        assert subscriber_id in call_args[0][1]
        assert "LOW_BALANCE" in call_args[0][1]


class TestInsertNotificationEvent:
    """Test insert_notification_event function."""

    @pytest.mark.asyncio
    async def test_insert_notification_event_with_valid_payload(self):
        """Should insert notification event with simulated status."""
        subscriber_id = str(uuid4())
        trace_id = str(uuid4())
        payload = {"balance_paise": 1000, "threshold_paise": 5000}
        db = MagicMock()
        db.execute = AsyncMock()

        await insert_notification_event(
            db=db,
            subscriber_id=subscriber_id,
            notification_type="LOW_BALANCE",
            channel="push",
            payload=payload,
            trace_id=trace_id,
        )

        db.execute.assert_called_once()
        call_args = db.execute.call_args
        assert "INSERT INTO notifications_events" in call_args[0][0]
        assert "uuid_generate_v7()" in call_args[0][0]
        assert "'simulated'" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_insert_notification_event_includes_trace_id(self):
        """Should include trace_id in the notification event."""
        subscriber_id = str(uuid4())
        trace_id = str(uuid4())
        payload = {"message": "Test notification"}
        db = MagicMock()
        db.execute = AsyncMock()

        await insert_notification_event(
            db=db,
            subscriber_id=subscriber_id,
            notification_type="DATA_NUDGE",
            channel="sms",
            payload=payload,
            trace_id=trace_id,
        )

        db.execute.assert_called_once()
        call_args = db.execute.call_args
        # Check that trace_id is included in the SQL call
        assert trace_id in call_args[0][1]
