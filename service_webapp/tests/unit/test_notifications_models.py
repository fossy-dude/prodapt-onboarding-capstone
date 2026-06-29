"""Unit tests for notification models (Story 4.2 Task 1).

Tests Pydantic models:
- NotificationTypeEnum
- NotificationPreferenceItem
- NotificationPreferencesResponse
- PatchNotificationPreferenceRequest
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.notifications import (
    NotificationPreferenceItem,
    NotificationPreferencesResponse,
    PatchNotificationPreferenceRequest,
)


class TestNotificationTypeEnum:
    """Test NotificationTypeEnum literal validation."""

    def test_valid_notification_types(self):
        """Should accept valid notification types."""
        valid_types = ["LOW_BALANCE", "BALANCE_DEPLETED", "USAGE_TRANSACTION", "PLAN_EXPIRY_REMINDER", "DATA_NUDGE"]
        for notification_type in valid_types:
            item = NotificationPreferenceItem(notification_type=notification_type, is_enabled=True)
            assert item.notification_type == notification_type

    def test_invalid_notification_type(self):
        """Should reject invalid notification types."""
        with pytest.raises(ValidationError):
            NotificationPreferenceItem(notification_type="INVALID_TYPE", is_enabled=True)


class TestNotificationPreferenceItem:
    """Test NotificationPreferenceItem model."""

    def test_create_preference_item(self):
        """Should create preference item with valid data."""
        item = NotificationPreferenceItem(notification_type="LOW_BALANCE", is_enabled=True)
        assert item.notification_type == "LOW_BALANCE"
        assert item.is_enabled is True

    def test_create_disabled_preference(self):
        """Should create preference item with is_enabled=False."""
        item = NotificationPreferenceItem(notification_type="BALANCE_DEPLETED", is_enabled=False)
        assert item.notification_type == "BALANCE_DEPLETED"
        assert item.is_enabled is False


class TestNotificationPreferencesResponse:
    """Test NotificationPreferencesResponse model."""

    def test_create_response_with_preferences(self):
        """Should create response with list of preferences."""
        preferences = [
            NotificationPreferenceItem(notification_type="LOW_BALANCE", is_enabled=True),
            NotificationPreferenceItem(notification_type="BALANCE_DEPLETED", is_enabled=False),
            NotificationPreferenceItem(notification_type="USAGE_TRANSACTION", is_enabled=True),
            NotificationPreferenceItem(notification_type="PLAN_EXPIRY_REMINDER", is_enabled=True),
            NotificationPreferenceItem(notification_type="DATA_NUDGE", is_enabled=False),
        ]
        response = NotificationPreferencesResponse(preferences=preferences)
        assert len(response.preferences) == 5
        assert response.preferences[0].notification_type == "LOW_BALANCE"
        assert response.preferences[0].is_enabled is True
        assert response.preferences[1].is_enabled is False

    def test_create_response_with_empty_preferences(self):
        """Should create response with empty preference list."""
        response = NotificationPreferencesResponse(preferences=[])
        assert len(response.preferences) == 0


class TestPatchNotificationPreferenceRequest:
    """Test PatchNotificationPreferenceRequest model."""

    def test_create_patch_request(self):
        """Should create patch request with valid data."""
        request = PatchNotificationPreferenceRequest(notification_type="LOW_BALANCE", is_enabled=False)
        assert request.notification_type == "LOW_BALANCE"
        assert request.is_enabled is False

    def test_create_enable_request(self):
        """Should create patch request to enable preference."""
        request = PatchNotificationPreferenceRequest(notification_type="DATA_NUDGE", is_enabled=True)
        assert request.notification_type == "DATA_NUDGE"
        assert request.is_enabled is True

    def test_invalid_type_in_patch_request(self):
        """Should reject patch request with invalid notification type."""
        with pytest.raises(ValidationError):
            PatchNotificationPreferenceRequest(notification_type="INVALID_TYPE", is_enabled=True)
