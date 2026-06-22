"""Unit tests for POST /api/v1/simulator/orders/{order_id}/advance (Story 1.7, AC #6).

Verifies forward-only state transitions and guardrails:
  - CREATED → KYC_PENDING
  - KYC_PENDING → KYC_VERIFIED
  - KYC_VERIFIED → ACTIVATED
  - 400 on terminal-state advance (ACTIVATED → *)
  - 404 for unknown order
  - Requires 'dev' role (401 without token, 403 with wrong role)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

ORDER_UUID = str(uuid.uuid4())


class FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple | None:
        return self._row


class FakeSimConn:
    """Tracks SELECT + UPDATE for the advance endpoint."""

    def __init__(self, initial_status: str | None) -> None:
        self._status = initial_status
        self.updates: list[str] = []

    async def execute(self, sql: str, params: tuple) -> FakeCursor:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT"):
            row = (self._status,) if self._status is not None else None
            return FakeCursor(row)
        if sql_upper.startswith("UPDATE"):
            self._status = params[0]
            self.updates.append(params[0])
            return FakeCursor(None)
        return FakeCursor(None)


class FakeSimDB:
    def __init__(self, initial_status: str | None) -> None:
        self.conn = FakeSimConn(initial_status)

    @asynccontextmanager
    async def transaction(self):
        yield self.conn

    async def ping(self) -> bool:
        return True


def _make_app(initial_status: str | None = "CREATED", role: str = "dev"):
    from main import create_app

    db = FakeSimDB(initial_status)
    jwt = FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": [role]})
    return create_app(db_adapter=db, jwt_validator=jwt)


async def _post(path: str, app, token: str = "Bearer fake-token") -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": token} if token else {}
        return await client.post(path, headers=headers)


# ── State machine transitions ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial,expected",
    [
        ("CREATED", "KYC_PENDING"),
        ("KYC_PENDING", "KYC_VERIFIED"),
        ("KYC_VERIFIED", "ACTIVATED"),
    ],
)
async def test_advance_forward_transitions(initial: str, expected: str):
    app = _make_app(initial_status=initial)
    r = await _post(f"/api/v1/simulator/orders/{ORDER_UUID}/advance", app)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["previous_status"] == initial
    assert body["data"]["status"] == expected
    assert body["data"]["order_id"] == ORDER_UUID


@pytest.mark.asyncio
async def test_advance_from_terminal_state_returns_400():
    app = _make_app(initial_status="ACTIVATED")
    r = await _post(f"/api/v1/simulator/orders/{ORDER_UUID}/advance", app)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ILLEGAL_TRANSITION"


@pytest.mark.asyncio
async def test_advance_unknown_order_returns_404():
    app = _make_app(initial_status=None)  # no order row
    r = await _post(f"/api/v1/simulator/orders/{uuid.uuid4()}/advance", app)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_advance_requires_dev_role():
    app = _make_app(role="subscriber")  # wrong role
    r = await _post(f"/api/v1/simulator/orders/{ORDER_UUID}/advance", app)
    assert r.status_code == 403
