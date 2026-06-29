"""Notification preferences router (Story 4.2 Task 3).

Endpoints:
- GET /api/v1/subscriber/notification-preferences
- PATCH /api/v1/subscriber/notification-preferences
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError
from core.responses import success_envelope
from db.notifications.commands import upsert_preference
from db.notifications.queries import get_preferences
from models.notifications import (
    NotificationPreferenceItem,
    NotificationPreferencesResponse,
    PatchNotificationPreferenceRequest,
)
from routers._identity import resolve_subscriber_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subscriber", tags=["notifications"])

# All notification types that must be returned by GET endpoint
_ALL_NOTIFICATION_TYPES = [
    "LOW_BALANCE",
    "BALANCE_DEPLETED",
    "USAGE_TRANSACTION",
    "PLAN_EXPIRY_REMINDER",
    "DATA_NUDGE",
]


def _db(request: Request):
    """Resolve the database adapter from app state."""
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised — lifespan may not have run.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


@router.get("/notification-preferences", status_code=200)
async def get_notification_preferences(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Get subscriber's notification preferences (AC #1, #2).

    Returns all notification types with their current opt-in status.
    If no preference row exists for a type, defaults to opted IN (is_enabled=true).
    """
    db = _db(request)

    async with db.transaction() as conn:
        subscriber_id = await resolve_subscriber_id(conn, jwt_payload)
        # Fetch existing preferences from DB
        existing_prefs = await get_preferences(conn, subscriber_id)

        # Build a map for quick lookup
        pref_map = {row["notification_type"]: row["is_enabled"] for row in existing_prefs}

        # Build full list of all types, defaulting to enabled
        preferences = []
        for notification_type in _ALL_NOTIFICATION_TYPES:
            is_enabled = pref_map.get(notification_type, True)  # Default to True
            preferences.append(NotificationPreferenceItem(notification_type=notification_type, is_enabled=is_enabled))  # type: ignore[arg-type]

    response = NotificationPreferencesResponse(preferences=preferences)
    return JSONResponse(
        status_code=200, content=success_envelope(response.model_dump(), trace_id=request.state.trace_id)
    )


@router.patch("/notification-preferences", status_code=200)
async def patch_notification_preference(
    request: Request,
    payload: PatchNotificationPreferenceRequest,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Update a single notification preference (AC #3).

    Persists the change to notifications_preferences table.
    Returns 422 if notification_type is not one of the 4 known types.
    """
    db = _db(request)

    async with db.transaction() as conn:
        subscriber_id = await resolve_subscriber_id(conn, jwt_payload)
        await upsert_preference(
            db=conn,
            subscriber_id=subscriber_id,
            notification_type=payload.notification_type,
            is_enabled=payload.is_enabled,
            channel="push",  # MVP default
        )

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"notification_type": payload.notification_type, "is_enabled": payload.is_enabled},
            trace_id=request.state.trace_id,
        ),
    )


__all__ = ["router"]
