"""Unit tests for NotificationTrigger (Story 4.1, Task 6).

Tests cover LOW_BALANCE and BALANCE_DEPLETED event publishing, deduplication
behavior, and threshold crossing logic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from consumer.notification_trigger import NotificationTrigger


@pytest.fixture
def mock_producer() -> MagicMock:
    """Mock Kafka producer."""
    producer = MagicMock()
    producer.publish = AsyncMock()
    return producer


@pytest.fixture
def trigger(mock_producer: MagicMock) -> NotificationTrigger:
    """Create NotificationTrigger with threshold=1000 paise."""
    return NotificationTrigger(
        producer=mock_producer,
        low_balance_threshold_paise=1000,
    )


@pytest.mark.asyncio
async def test_low_balance_fires_when_balance_below_threshold(trigger: NotificationTrigger) -> None:
    """AC #1: LOW_BALANCE fires when balance_after=500, threshold=1000."""
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 1
    call_args = trigger.producer.publish.call_args
    assert call_args.kwargs["topic"] == "notification.events"
    assert call_args.kwargs["key"] == "9876543210"

    envelope = call_args.kwargs["envelope"]
    assert envelope.event_type == "notification.balance"
    assert envelope.payload["type"] == "LOW_BALANCE"
    assert envelope.payload["subscriber_id"] == "sub-123"
    assert envelope.payload["msisdn_last4"] == "3210"
    assert envelope.payload["balance_paise"] == 500
    assert envelope.payload["threshold_paise"] == 1000


@pytest.mark.asyncio
async def test_balance_depleted_fires_when_balance_zero(trigger: NotificationTrigger) -> None:
    """AC #3: BALANCE_DEPLETED fires when balance_after=0."""
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=0,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 1
    call_args = trigger.producer.publish.call_args
    envelope = call_args.kwargs["envelope"]
    assert envelope.event_type == "notification.balance"
    assert envelope.payload["type"] == "BALANCE_DEPLETED"
    assert envelope.payload["subscriber_id"] == "sub-123"
    assert envelope.payload["msisdn_last4"] == "3210"


@pytest.mark.asyncio
async def test_balance_depleted_fires_when_balance_negative(trigger: NotificationTrigger) -> None:
    """AC #3: BALANCE_DEPLETED fires when balance_after=-100 (overdraft)."""
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=-100,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 1
    envelope = trigger.producer.publish.call_args.kwargs["envelope"]
    assert envelope.payload["type"] == "BALANCE_DEPLETED"


@pytest.mark.asyncio
async def test_no_event_when_balance_above_threshold(trigger: NotificationTrigger) -> None:
    """No notification fires when balance_after=2000, threshold=1000."""
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=2000,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 0


@pytest.mark.asyncio
async def test_low_balance_dedup_multiple_calls_below_threshold(trigger: NotificationTrigger) -> None:
    """Dedup: second LOW_BALANCE below threshold for same msisdn is suppressed."""
    # First call: should fire
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )

    # Second call with same msisdn still below threshold: should NOT fire
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=400,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 1  # Only first call fired


@pytest.mark.asyncio
async def test_balance_depleted_dedup_multiple_calls_at_zero(trigger: NotificationTrigger) -> None:
    """Dedup: second BALANCE_DEPLETED for same msisdn is suppressed."""
    # First call: should fire
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=0,
        trace_id="a" * 32,
    )

    # Second call: should NOT fire
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=0,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 1


@pytest.mark.asyncio
async def test_different_subscribers_generate_separate_events(trigger: NotificationTrigger) -> None:
    """Different msisdns generate separate LOW_BALANCE events."""
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )

    await trigger.check_and_publish(
        msisdn="9123456780",
        subscriber_id="sub-456",
        balance_after=500,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 2


@pytest.mark.asyncio
async def test_clear_notified_allows_refire(trigger: NotificationTrigger) -> None:
    """After clear_notified, LOW_BALANCE can fire again for same msisdn."""
    # First call: fires
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )
    assert trigger.producer.publish.call_count == 1

    # Clear notification state (simulating recharge)
    trigger.clear_notified("9876543210")

    # Second call: should fire again
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )
    assert trigger.producer.publish.call_count == 2


@pytest.mark.asyncio
async def test_clear_notified_clears_both_low_balance_and_depleted(trigger: NotificationTrigger) -> None:
    """clear_notified clears both LOW_BALANCE and BALANCE_DEPLETED entries."""
    # Trigger LOW_BALANCE
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )

    # Trigger BALANCE_DEPLETED (simulating further deductions)
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=0,
        trace_id="a" * 32,
    )

    assert trigger.producer.publish.call_count == 2
    assert len(trigger._notified) == 2  # Both events tracked

    # Clear all notifications for this msisdn
    trigger.clear_notified("9876543210")
    assert len(trigger._notified) == 0


@pytest.mark.asyncio
async def test_balance_crosses_below_then_above_threshold(trigger: NotificationTrigger) -> None:
    """Balance crossing below threshold fires event; crossing above clears entry."""
    # Balance drops below threshold: should fire LOW_BALANCE
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )
    assert trigger.producer.publish.call_count == 1

    # Balance rises above threshold (recharge): should clear LOW_BALANCE entry
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=2000,
        trace_id="a" * 32,
    )
    assert trigger.producer.publish.call_count == 1  # No new event
    assert len(trigger._notified) == 0  # Entry cleared

    # Balance drops below threshold again: should fire LOW_BALANCE again
    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id="a" * 32,
    )
    assert trigger.producer.publish.call_count == 2  # Second event fired


@pytest.mark.asyncio
async def test_trace_id_propagated_to_envelope(trigger: NotificationTrigger) -> None:
    """Trace ID from CDR is propagated to notification envelope."""
    trace_id = "0123456789abcdef0123456789abcdef"  # 32 hex chars

    await trigger.check_and_publish(
        msisdn="9876543210",
        subscriber_id="sub-123",
        balance_after=500,
        trace_id=trace_id,
    )

    envelope = trigger.producer.publish.call_args.kwargs["envelope"]
    assert envelope.trace_id == trace_id
