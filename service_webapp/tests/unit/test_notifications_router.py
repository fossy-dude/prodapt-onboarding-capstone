"""Unit tests for notifications router (Story 4.2 Task 3).

Tests endpoints:
- GET /api/v1/subscriber/notification-preferences
- PATCH /api/v1/subscriber/notification-preferences
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator
from db.notifications.commands import insert_notification_event, upsert_preference
from db.notifications.queries import get_preferences

if TYPE_CHECKING:
    from collections.abc import Callable


_SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _sub_payload(sub_id: str = _SUB_A, groups: list[str] | None = None) -> dict:
    return {"sub": sub_id, "cognito:groups": groups or ["subscriber"], "phone_number": "919876543210"}


def _make_app(
    *,
    db=None,
    jwt_payload: dict | None = None,
):
    from main import create_app

    return create_app(
        db_adapter=db or _FakeDb(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload()),
    )


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeRow:
    """Fake psycopg3 row object that can be converted to dict."""

    def __init__(self, notification_type: str, is_enabled: bool) -> None:
        self._data = {"notification_type": notification_type, "is_enabled": is_enabled}

    def __iter__(self):
        return iter(self._data.items())

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key):
        return self._data[key]


class _FakeCursor:
    def __init__(self, *, row: tuple | None = None, rows: list | None = None) -> None:
        self._row = row
        self._rows = rows or []

    async def fetchone(self) -> tuple | None:
        return self._row

    async def fetchall(self) -> list:
        return self._rows


class _FakeConn:
    def __init__(
        self,
        *,
        pref_rows: list[tuple] | None = None,
    ) -> None:
        # Convert tuples to FakeRow objects
        self._pref_rows = [_FakeRow(nt, ie) for nt, ie in pref_rows] if pref_rows else []

    async def execute(self, sql: str, params=None):
        lowered = sql.lower()
        if "notifications_preferences" in lowered and "select" in lowered:
            return _FakeCursor(rows=self._pref_rows)
        if "identity_subscribers" in lowered:
            # Return the test subscriber UUID for the resolver lookup
            return _FakeCursor(row=(_SUB_A,))
        return _FakeCursor()


class _FakeDb:
    def __init__(self, *, pref_rows: list[tuple] | None = None) -> None:
        self._pref_rows = pref_rows or []

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(pref_rows=self._pref_rows)

    async def ping(self) -> bool:
        return True


# ── GET /notification-preferences tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_preferences_returns_all_types_with_defaults():
    """Should return all 4 notification types with defaults when no DB rows exist."""
    app = _make_app(db=_FakeDb(pref_rows=[]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/notification-preferences", headers={"Authorization": "Bearer tok"})

    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["preferences"]) == 4
    # All should be enabled by default
    for pref in data["preferences"]:
        assert pref["is_enabled"] is True


@pytest.mark.asyncio
async def test_get_preferences_returns_existing_preferences():
    """Should return existing preferences when DB rows exist."""
    # Simulate DB rows for LOW_BALANCE (enabled) and BALANCE_DEPLETED (disabled)
    pref_rows = [
        ("LOW_BALANCE", True),
        ("BALANCE_DEPLETED", False),
    ]
    app = _make_app(db=_FakeDb(pref_rows=pref_rows))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/notification-preferences", headers={"Authorization": "Bearer tok"})

    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["preferences"]) == 4

    # LOW_BALANCE should be enabled
    low_balance = next(p for p in data["preferences"] if p["notification_type"] == "LOW_BALANCE")
    assert low_balance["is_enabled"] is True

    # BALANCE_DEPLETED should be disabled
    balance_depleted = next(p for p in data["preferences"] if p["notification_type"] == "BALANCE_DEPLETED")
    assert balance_depleted["is_enabled"] is False

    # Other types should default to enabled
    plan_expiry = next(p for p in data["preferences"] if p["notification_type"] == "PLAN_EXPIRY_REMINDER")
    assert plan_expiry["is_enabled"] is True


@pytest.mark.asyncio
async def test_get_preferences_no_token_401():
    """Auth matrix: missing token → 401."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/notification-preferences")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_preferences_wrong_role_403():
    """Auth matrix: valid token but wrong role → 403."""
    payload = _sub_payload(groups=["admin"])
    app = _make_app(jwt_payload=payload)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/notification-preferences", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403


# ── PATCH /notification-preferences tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_preference_updates_enabled_state():
    """Should update preference when valid data is provided."""
    app = _make_app()
    transport = ASGITransport(app=app)
    payload = {"notification_type": "LOW_BALANCE", "is_enabled": False}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            "/api/v1/subscriber/notification-preferences", json=payload, headers={"Authorization": "Bearer tok"}
        )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["notification_type"] == "LOW_BALANCE"
    assert data["is_enabled"] is False


@pytest.mark.asyncio
async def test_patch_preference_rejects_invalid_type():
    """Should return 422 when notification_type is invalid."""
    app = _make_app()
    transport = ASGITransport(app=app)
    payload = {"notification_type": "INVALID_TYPE", "is_enabled": False}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            "/api/v1/subscriber/notification-preferences", json=payload, headers={"Authorization": "Bearer tok"}
        )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_preference_no_token_401():
    """Auth matrix: missing token → 401."""
    app = _make_app()
    transport = ASGITransport(app=app)
    payload = {"notification_type": "LOW_BALANCE", "is_enabled": False}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch("/api/v1/subscriber/notification-preferences", json=payload)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_patch_preference_wrong_role_403():
    """Auth matrix: valid token but wrong role → 403."""
    payload = _sub_payload(groups=["admin"])
    app = _make_app(jwt_payload=payload)
    transport = ASGITransport(app=app)
    patch_payload = {"notification_type": "LOW_BALANCE", "is_enabled": False}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            "/api/v1/subscriber/notification-preferences", json=patch_payload, headers={"Authorization": "Bearer tok"}
        )
    assert r.status_code == 403
