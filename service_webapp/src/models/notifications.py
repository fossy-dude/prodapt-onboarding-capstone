"""Pydantic models for notification preferences (Story 4.2).

Notification types and preference management:
- NotificationTypeEnum: Literal for valid notification types
- NotificationPreferenceItem: Single preference item
- NotificationPreferencesResponse: Response for GET /notification-preferences
- PatchNotificationPreferenceRequest: Request for PATCH /notification-preferences
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationTypeEnum:
    """Literal types for notification preferences."""

    LOW_BALANCE: Literal["LOW_BALANCE"] = "LOW_BALANCE"
    BALANCE_DEPLETED: Literal["BALANCE_DEPLETED"] = "BALANCE_DEPLETED"
    PLAN_EXPIRY_REMINDER: Literal["PLAN_EXPIRY_REMINDER"] = "PLAN_EXPIRY_REMINDER"
    DATA_NUDGE: Literal["DATA_NUDGE"] = "DATA_NUDGE"


# Define the literal type for validation
NotificationTypeLiteral = Literal[
    "LOW_BALANCE",
    "BALANCE_DEPLETED",
    "PLAN_EXPIRY_REMINDER",
    "DATA_NUDGE",
]


class NotificationPreferenceItem(BaseModel):
    """Single notification preference item."""

    model_config = ConfigDict(extra="forbid")

    notification_type: NotificationTypeLiteral = Field(
        ..., description="Type of notification: LOW_BALANCE, BALANCE_DEPLETED, PLAN_EXPIRY_REMINDER, or DATA_NUDGE"
    )
    is_enabled: bool = Field(..., description="Whether this notification type is enabled for the subscriber")


class NotificationPreferencesResponse(BaseModel):
    """Response body for GET /api/v1/subscriber/notification-preferences."""

    model_config = ConfigDict(extra="forbid")

    preferences: list[NotificationPreferenceItem] = Field(
        ..., description="List of all notification preferences for the subscriber"
    )


class PatchNotificationPreferenceRequest(BaseModel):
    """Request body for PATCH /api/v1/subscriber/notification-preferences."""

    model_config = ConfigDict(extra="forbid")

    notification_type: NotificationTypeLiteral = Field(
        ...,
        description="Notification type to update (one of LOW_BALANCE, BALANCE_DEPLETED, PLAN_EXPIRY_REMINDER, DATA_NUDGE)",
    )
    is_enabled: bool = Field(..., description="New enabled state for this notification type")


__all__ = [
    "NotificationPreferenceItem",
    "NotificationPreferencesResponse",
    "NotificationTypeLiteral",
    "PatchNotificationPreferenceRequest",
]
