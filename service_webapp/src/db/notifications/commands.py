"""DB commands for notification preferences (Story 4.2 Task 2)."""

from __future__ import annotations

import json


async def upsert_preference(
    db,
    subscriber_id: str,
    notification_type: str,
    is_enabled: bool,
    channel: str = "push",
) -> None:
    """Insert or update a notification preference for a subscriber.

    Uses ON CONFLICT to handle both insert and update cases.

    Args:
        db: Database connection with execute method
        subscriber_id: UUID string of subscriber
        notification_type: Type of notification (LOW_BALANCE, BALANCE_DEPLETED, etc.)
        is_enabled: Whether this notification type is enabled
        channel: Notification channel (default: 'push' for MVP)
    """
    sql = """
        INSERT INTO notifications_preferences (
            id, subscriber_id, notification_type, channel, is_enabled, created_at, modified_at
        )
        VALUES (
            gen_random_uuid(), %s, %s, %s, %s, NOW(), NOW()
        )
        ON CONFLICT (subscriber_id, notification_type, channel)
        DO UPDATE SET
            is_enabled = EXCLUDED.is_enabled,
            modified_at = NOW()
    """

    await db.execute(sql, (subscriber_id, notification_type, channel, is_enabled))


async def insert_notification_event(
    db,
    subscriber_id: str,
    notification_type: str,
    channel: str,
    payload: dict,
    trace_id: str,
) -> None:
    """Insert a simulated notification event.

    Uses DB-side uuid_generate_v7() to avoid Python UUID generation.

    Args:
        db: Database connection with execute method
        subscriber_id: UUID string of subscriber
        notification_type: Type of notification
        channel: Notification channel
        payload: Event payload (will be serialized to JSONB)
        trace_id: Trace ID for distributed tracing
    """
    sql = """
        INSERT INTO notifications_events (
            id, subscriber_id, notification_type, channel, status,
            payload, sent_at, created_at, modified_at
        )
        VALUES (
            uuid_generate_v7(), %s, %s, %s, 'simulated', %s::jsonb, NOW(), NOW(), NOW()
        )
    """

    payload_json = json.dumps(payload)
    await db.execute(sql, (subscriber_id, notification_type, channel, payload_json, trace_id))


__all__ = ["insert_notification_event", "upsert_preference"]
