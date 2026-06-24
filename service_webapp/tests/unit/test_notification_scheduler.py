"""Unit tests for PLAN_EXPIRY_REMINDER scheduler (Story 4.1, Task 6).

Tests cover:
- 2 subscribers expiring in 2 days → producer.send_and_wait called twice with PLAN_EXPIRY_REMINDER
- Zero subscribers → no calls
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_producer() -> MagicMock:
    producer = MagicMock()
    producer.send_and_wait = AsyncMock()
    return producer


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_run_plan_expiry_check_publishes_for_expiring_subscribers(
    mock_db: MagicMock, mock_producer: MagicMock
) -> None:
    """2 subscribers with plans expiring in 2 days → 2 PLAN_EXPIRY_REMINDER events."""
    from services.notification_scheduler import run_plan_expiry_check

    expiry_date = date.today() + timedelta(days=2)

    # DB returns 2 subscribers
    mock_conn = AsyncMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall = AsyncMock(
        return_value=[
            ("sub-001", "9876543210", expiry_date),
            ("sub-002", "9123456780", expiry_date),
        ]
    )
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    # Wire transaction context manager
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=None))
    )

    await run_plan_expiry_check(mock_db, mock_producer, lead_days=3)

    assert mock_producer.send_and_wait.call_count == 2

    # Verify first call
    first_call = mock_producer.send_and_wait.call_args_list[0]
    assert first_call.args[0] == "notification.events"
    payload = first_call.kwargs["value"]["payload"]
    assert payload["type"] == "PLAN_EXPIRY_REMINDER"
    assert payload["subscriber_id"] == "sub-001"
    assert payload["msisdn_last4"] == "3210"
    assert payload["expiry_date"] == expiry_date.isoformat()
    assert payload["days_remaining"] == 2

    # Verify second call
    second_call = mock_producer.send_and_wait.call_args_list[1]
    payload2 = second_call.kwargs["value"]["payload"]
    assert payload2["subscriber_id"] == "sub-002"
    assert payload2["msisdn_last4"] == "6780"


@pytest.mark.asyncio
async def test_run_plan_expiry_check_no_calls_when_no_subscribers(mock_db: MagicMock, mock_producer: MagicMock) -> None:
    """Zero subscribers expiring → no producer calls."""
    from services.notification_scheduler import run_plan_expiry_check

    mock_conn = AsyncMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    mock_db.transaction = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=None))
    )

    await run_plan_expiry_check(mock_db, mock_producer, lead_days=3)

    assert mock_producer.send_and_wait.call_count == 0


@pytest.mark.asyncio
async def test_run_plan_expiry_check_includes_days_remaining(mock_db: MagicMock, mock_producer: MagicMock) -> None:
    """days_remaining is correctly computed from today."""
    from services.notification_scheduler import run_plan_expiry_check

    expiry_date = date.today() + timedelta(days=1)

    mock_conn = AsyncMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall = AsyncMock(return_value=[("sub-001", "9876543210", expiry_date)])
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=None))
    )

    await run_plan_expiry_check(mock_db, mock_producer, lead_days=3)

    payload = mock_producer.send_and_wait.call_args.kwargs["value"]["payload"]
    assert payload["days_remaining"] == 1
    assert payload["expiry_date"] == expiry_date.isoformat()


@pytest.mark.asyncio
async def test_run_plan_expiry_check_event_keyed_by_msisdn(mock_db: MagicMock, mock_producer: MagicMock) -> None:
    """Kafka message key is the msisdn (as bytes)."""
    from services.notification_scheduler import run_plan_expiry_check

    expiry_date = date.today() + timedelta(days=2)
    mock_conn = AsyncMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall = AsyncMock(return_value=[("sub-001", "9876543210", expiry_date)])
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=None))
    )

    await run_plan_expiry_check(mock_db, mock_producer, lead_days=3)

    call_kwargs = mock_producer.send_and_wait.call_args.kwargs
    assert call_kwargs["key"] == b"9876543210"
