"""Unit tests for GET /api/v1/subscriber/orders/{order_id}/status (Story 1.7, AC #2, #5).

Uses in-memory fakes for the DB adapter and JWT validator — no Postgres or AWS
dependency. Verifies:
  - Standard envelope shape on success
  - HTTP 403 when JWT ``sub`` ≠ order's ``subscriber_id``
  - HTTP 404 for unknown order
  - MSISDN absent in response until status = 'ACTIVATED'
  - HTTP 200 + MSISDN present when status = 'ACTIVATED'
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

SUBSCRIBER_UUID = str(uuid.uuid4())
OTHER_UUID = str(uuid.uuid4())
ORDER_UUID = str(uuid.uuid4())
MSISDN = "9876543210"
UPDATED_AT = datetime(2026, 6, 22, 10, 0, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple | None:
        return self._row


class FakeConn:
    """Minimal async connection stub for read queries."""

    def __init__(self, rows: dict[str, tuple | None]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple) -> FakeCursor:
        self.executed.append((sql, params))
        key = str(params[0])
        return FakeCursor(self._rows.get(key))


class FakeDB:
    """Fake DatabaseProtocol that returns pre-configured rows via ``transaction()``."""

    def __init__(self, rows: dict[str, tuple | None]) -> None:
        self._rows = rows
        self.conn = FakeConn(rows)

    @asynccontextmanager
    async def transaction(self):
        yield self.conn

    async def ping(self) -> bool:
        return True


def _make_app(
    order_row: tuple | None = None,
    active_row: tuple | None = None,
    sub: str = SUBSCRIBER_UUID,
):
    """Build a test app with fake JWT + DB injected."""
    from main import create_app

    rows: dict[str, tuple | None] = {}
    if order_row is not None:
        rows[ORDER_UUID] = order_row
    if active_row is not None:
        rows[SUBSCRIBER_UUID] = active_row

    db = FakeDB(rows)
    jwt = FakeJWTValidator({"sub": sub, "cognito:groups": ["subscriber"]})
    return create_app(db_adapter=db, jwt_validator=jwt)


async def _get(path: str, app) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": "Bearer fake-token"})


# ── GET /orders/{order_id}/status ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_status_returns_envelope_for_created_state():
    row = ("CREATED", UPDATED_AT, SUBSCRIBER_UUID, MSISDN)
    app = _make_app(order_row=row)
    r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "CREATED"
    assert body["data"]["msisdn"] is None  # not yet ACTIVATED
    assert "updated_at" in body["data"]
    assert "trace_id" in body["meta"]
    assert "timestamp" in body["meta"]


@pytest.mark.asyncio
async def test_order_status_returns_msisdn_only_when_activated():
    row = ("ACTIVATED", UPDATED_AT, SUBSCRIBER_UUID, MSISDN)
    app = _make_app(order_row=row)
    r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
    assert r.status_code == 200
    assert r.json()["data"]["msisdn"] == MSISDN


@pytest.mark.asyncio
async def test_order_status_msisdn_absent_for_kyc_pending():
    for status in ("KYC_PENDING", "KYC_VERIFIED"):
        row = (status, UPDATED_AT, SUBSCRIBER_UUID, MSISDN)
        app = _make_app(order_row=row)
        r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
        assert r.status_code == 200, f"expected 200 for status={status}"
        assert r.json()["data"]["msisdn"] is None, f"msisdn should be None for status={status}"


@pytest.mark.asyncio
async def test_order_status_403_when_sub_mismatch():
    row = ("CREATED", UPDATED_AT, OTHER_UUID, MSISDN)  # order belongs to OTHER_UUID
    app = _make_app(order_row=row, sub=SUBSCRIBER_UUID)  # JWT is SUBSCRIBER_UUID
    r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_order_status_404_for_unknown_order():
    app = _make_app()  # no rows configured
    r = await _get(f"/api/v1/subscriber/orders/{uuid.uuid4()}/status", app)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
