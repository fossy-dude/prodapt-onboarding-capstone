"""DB queries for notification preferences (Story 4.2 Task 2)."""

from __future__ import annotations

from collections.abc import Mapping


async def get_preferences(db, subscriber_id: str) -> list[Mapping]:
    """Get notification preferences for a subscriber.

    Args:
        db: Database connection with execute method
        subscriber_id: UUID string of subscriber

    Returns:
        List of dicts with keys: notification_type, is_enabled
        Returns empty list if no preferences exist
    """
    sql = """
        SELECT notification_type, is_enabled
        FROM notifications_preferences
        WHERE subscriber_id = %s
    """
    cursor = await db.execute(sql, (subscriber_id,))
    rows = await cursor.fetchall()

    # Convert to list of dicts for easier handling
    return [dict(row) for row in rows]


__all__ = ["get_preferences"]
