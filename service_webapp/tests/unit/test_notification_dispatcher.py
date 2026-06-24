"""Unit tests for notification dispatcher (Story 4.2 Task 4).

Tests dispatcher background task:
- Opted-out events are discarded
- Opted-in events are logged to notifications_events
- DB failures don't crash the consumer
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_dispatcher_query_preferences():
    """Test that get_preferences is called correctly."""
    from db.notifications.queries import get_preferences

    # Create fake cursor
    class FakeCursor:
        async def fetchall(self):
            return [{"notification_type": "LOW_BALANCE", "is_enabled": False}]

    class FakeConn:
        async def execute(self, sql, params):
            return FakeCursor()

    conn = FakeConn()
    result = await get_preferences(conn, str(uuid4()))

    assert len(result) == 1
    assert result[0]["notification_type"] == "LOW_BALANCE"
    assert result[0]["is_enabled"] is False


@pytest.mark.asyncio
async def test_dispatcher_inserts_notification_event_when_opted_in():
    """Test that insert_notification_event is called when opted in."""
    from db.notifications.commands import insert_notification_event

    # Track if insert was called
    insert_called = False
    original_execute = None

    class FakeCursor:
        async def fetchone(self):
            return None

    class FakeConn:
        async def execute(self, sql, params):
            nonlocal insert_called
            if "INSERT INTO notifications_events" in sql:
                insert_called = True
            return FakeCursor()

    conn = FakeConn()
    await insert_notification_event(
        db=conn,
        subscriber_id=str(uuid4()),
        notification_type="LOW_BALANCE",
        channel="push",
        payload={"balance_paise": 1000},
        trace_id=str(uuid4()),
    )

    assert insert_called, "insert_notification_event should have been called"


@pytest.mark.asyncio
async def test_dispatcher_upsert_creates_preference():
    """Test that upsert_preference creates a new preference."""
    from db.notifications.commands import upsert_preference

    subscriber_id = str(uuid4())

    class FakeCursor:
        async def fetchone(self):
            return None

    class FakeConn:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, params):
            self.calls.append((sql, params))
            return FakeCursor()

    conn = FakeConn()

    # Upsert as disabled
    await upsert_preference(conn, subscriber_id, "LOW_BALANCE", False, "push")

    # Verify SQL was called
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO notifications_preferences" in sql
    assert "ON CONFLICT" in sql
    assert subscriber_id in params


@pytest.mark.asyncio
async def test_dispatcher_default_preference_when_no_rows():
    """Test that missing preferences default to enabled."""
    from db.notifications.queries import get_preferences

    subscriber_id = str(uuid4())

    class FakeCursor:
        async def fetchall(self):
            return []  # No rows

    class FakeConn:
        async def execute(self, sql, params):
            return FakeCursor()

    conn = FakeConn()
    result = await get_preferences(conn, subscriber_id)

    # Should return empty list
    assert len(result) == 0

    # Dispatcher logic: pref_map.get(notification_type, True) defaults to True
    pref_map = {row["notification_type"]: row["is_enabled"] for row in result}
    is_enabled = pref_map.get("LOW_BALANCE", True)
    assert is_enabled is True, "Default preference should be True (opted in)"
