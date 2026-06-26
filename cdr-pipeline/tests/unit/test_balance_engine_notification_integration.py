"""Unit tests for BalanceEngine + NotificationTrigger integration (Story 4.1, Task 3).

Tests that NotificationTrigger is wired into BalanceEngine correctly and that
notifications fire during balance deductions.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from consumer.balance_writer import BalanceEngine
from consumer.notification_trigger import NotificationTrigger


@pytest.fixture
def mock_cache() -> MagicMock:
    """Mock Valkey cache."""
    cache = MagicMock()
    cache.incr_by = AsyncMock(return_value=5000)
    cache.get_str = AsyncMock(return_value="5000")
    return cache


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock Postgres adapter."""
    db = MagicMock()
    db.transaction = MagicMock()
    return db


@pytest.fixture
def mock_producer() -> MagicMock:
    """Mock Kafka producer."""
    producer = MagicMock()
    producer.publish = AsyncMock()
    return producer


@pytest.fixture
def notification_trigger(mock_producer: MagicMock) -> NotificationTrigger:
    """Create NotificationTrigger with threshold=1000 paise."""
    return NotificationTrigger(
        producer=mock_producer,
        low_balance_threshold_paise=1000,
    )


@pytest.mark.asyncio
async def test_balance_engine_accepts_notification_trigger(
    mock_cache: MagicMock, mock_db: MagicMock, notification_trigger: NotificationTrigger
) -> None:
    """BalanceEngine __init__ accepts optional notification_trigger parameter."""
    engine = BalanceEngine(
        cache=mock_cache,
        db=mock_db,
        notification_trigger=notification_trigger,
    )

    assert engine._notification_trigger is notification_trigger


@pytest.mark.asyncio
async def test_balance_engine_default_notification_trigger_is_none(
    mock_cache: MagicMock,
    mock_db: MagicMock,
) -> None:
    """BalanceEngine defaults to notification_trigger=None when not provided."""
    engine = BalanceEngine(
        cache=mock_cache,
        db=mock_db,
    )

    assert engine._notification_trigger is None


@pytest.mark.asyncio
async def test_set_notification_trigger_injects_trigger(
    mock_cache: MagicMock, mock_db: MagicMock, notification_trigger: NotificationTrigger
) -> None:
    """set_notification_trigger() method injects trigger into existing engine."""
    engine = BalanceEngine(
        cache=mock_cache,
        db=mock_db,
    )

    # Initially None
    assert engine._notification_trigger is None

    # Inject trigger
    engine.set_notification_trigger(notification_trigger)

    # Now wired
    assert engine._notification_trigger is notification_trigger


@pytest.mark.asyncio
async def test_deduct_calls_notification_trigger_when_wired(
    mock_cache: MagicMock,
    mock_db: MagicMock,
    mock_producer: MagicMock,
) -> None:
    """When notification_trigger is wired, deduct() calls check_and_publish()."""
    # Build subscriber→msisdn index (normally done by warmup)
    mock_cache.incr_by = AsyncMock(return_value=500)  # Low balance

    trigger = NotificationTrigger(
        producer=mock_producer,
        low_balance_threshold_paise=1000,
    )

    engine = BalanceEngine(
        cache=mock_cache,
        db=mock_db,
        notification_trigger=trigger,
    )

    # Manually set the index (bypass warmup for unit test)
    engine._subscriber_to_msisdn = {"00000000-0000-0000-0000-000000000003": "9876543210"}
    engine._msisdn_to_subscriber = {"9876543210": "00000000-0000-0000-0000-000000000003"}

    # Create a mock CDR - use VoiceCdr (concrete type)
    from uuid import UUID

    from models.cdr import VoiceCdr

    cdr = VoiceCdr(
        cdr_id=UUID("00000000-0000-0000-0000-000000000001"),
        session_id=UUID("00000000-0000-0000-0000-000000000002"),
        subscriber_id=UUID("00000000-0000-0000-0000-000000000003"),
        telecom_circle="KA",
        cost_paise=500,
        start_time="2024-01-01T00:00:00Z",
        cdr_type="voice",
        from_number="+919876543210",
        to_number="+919123456780",
        call_direction="MO",
        duration_seconds=60,
        call_status="answered",
    )

    # Run deduct
    await engine.deduct(cdr)

    # Wait for async notification task to complete (fire-and-forget via create_task)
    await asyncio.sleep(0.1)

    # Verify notification was published
    assert mock_producer.publish.call_count == 1
    envelope = mock_producer.publish.call_args.kwargs["envelope"]
    assert envelope.payload["type"] == "LOW_BALANCE"


@pytest.mark.asyncio
async def test_deduct_skips_notification_trigger_when_none(
    mock_cache: MagicMock,
    mock_db: MagicMock,
) -> None:
    """When notification_trigger is None, deduct() does not crash."""
    mock_cache.incr_by = AsyncMock(return_value=500)

    engine = BalanceEngine(
        cache=mock_cache,
        db=mock_db,
        notification_trigger=None,  # Explicitly None
    )

    # Manually set the index
    engine._subscriber_to_msisdn = {"00000000-0000-0000-0000-000000000003": "9876543210"}
    engine._msisdn_to_subscriber = {"9876543210": "00000000-0000-0000-0000-000000000003"}

    # Create a mock CDR - use VoiceCdr (concrete type)
    from uuid import UUID

    from models.cdr import VoiceCdr

    cdr = VoiceCdr(
        cdr_id=UUID("00000000-0000-0000-0000-000000000001"),
        session_id=UUID("00000000-0000-0000-0000-000000000002"),
        subscriber_id=UUID("00000000-0000-0000-0000-000000000003"),
        telecom_circle="KA",
        cost_paise=500,
        start_time="2024-01-01T00:00:00Z",
        cdr_type="voice",
        from_number="+919876543210",
        to_number="+919123456780",
        call_direction="MO",
        duration_seconds=60,
        call_status="answered",
    )

    # Should not crash
    await engine.deduct(cdr)


@pytest.mark.asyncio
async def test_deduct_uses_asyncio_create_task_for_fire_and_forget(
    mock_cache: MagicMock,
    mock_db: MagicMock,
    mock_producer: MagicMock,
) -> None:
    """deduct() uses asyncio.create_task() for fire-and-forget notification check."""
    # Track if task was created
    task_created = False
    original_create_task = asyncio.create_task

    def mock_create_task(coro):
        nonlocal task_created
        task_created = True
        return original_create_task(coro)

    asyncio.create_task = mock_create_task

    try:
        mock_cache.incr_by = AsyncMock(return_value=500)

        trigger = NotificationTrigger(
            producer=mock_producer,
            low_balance_threshold_paise=1000,
        )

        engine = BalanceEngine(
            cache=mock_cache,
            db=mock_db,
            notification_trigger=trigger,
        )

        engine._subscriber_to_msisdn = {"00000000-0000-0000-0000-000000000003": "9876543210"}
        engine._msisdn_to_subscriber = {"9876543210": "00000000-0000-0000-0000-000000000003"}

        from uuid import UUID

        from models.cdr import VoiceCdr

        cdr = VoiceCdr(
            cdr_id=UUID("00000000-0000-0000-0000-000000000001"),
            session_id=UUID("00000000-0000-0000-0000-000000000002"),
            subscriber_id=UUID("00000000-0000-0000-0000-000000000003"),
            telecom_circle="KA",
            cost_paise=500,
            start_time="2024-01-01T00:00:00Z",
            cdr_type="voice",
            from_number="+919876543210",
            to_number="+919123456780",
            call_direction="MO",
            duration_seconds=60,
            call_status="answered",
        )

        await engine.deduct(cdr)

        # Verify asyncio.create_task was called
        assert task_created
    finally:
        asyncio.create_task = original_create_task
