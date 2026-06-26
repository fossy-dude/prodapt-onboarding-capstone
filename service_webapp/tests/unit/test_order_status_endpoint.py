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
OTHER_MSISDN = "9876543211"
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
        lowered = sql.lower()
        # Handle subscriber lookup for resolve_subscriber_id
        # The resolver query is: SELECT id FROM identity_subscribers WHERE msisdn IN (%s, %s)
        # It only selects id and has WHERE msisdn IN clause
        if (
            "identity_subscribers" in lowered
            and "select id" in lowered
            and "where msisdn" in lowered
            and "in (" in lowered
        ):
            # This is specifically the subscriber lookup query
            return FakeCursor((SUBSCRIBER_UUID,))
        # For order status queries (JOINs identity_subscribers), use the order_id as the key
        if "ops_order_fulfilment" in lowered and params and len(params) > 0:
            key = str(params[0])
            return FakeCursor(self._rows.get(key))
        # For active order queries
        if "ops_order_fulfilment" in lowered and params and len(params) > 0:
            key = str(params[0])
            return FakeCursor(self._rows.get(key))
        return FakeCursor(None)


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
    msisdn: str = MSISDN,
):
    """Build a test app with fake JWT + DB injected."""
    from main import create_app

    rows: dict[str, tuple | None] = {}
    if order_row is not None:
        rows[ORDER_UUID] = order_row
    if active_row is not None:
        rows[SUBSCRIBER_UUID] = active_row

    db = FakeDB(rows)
    jwt = FakeJWTValidator({"sub": sub, "cognito:groups": ["subscriber"], "phone_number": msisdn})
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


@pytest.mark.asyncio
async def test_order_status_query_joins_identity_subscribers():
    """Assert the status query JOINs identity_subscribers (P10).

    A regression that drops the JOIN (MSISDN always None) must fail this test.
    """
    row = ("CREATED", UPDATED_AT, SUBSCRIBER_UUID, MSISDN)
    app = _make_app(order_row=row)
    r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
    assert r.status_code == 200
    executed_sql = app.state.db_adapter.conn.executed[-1][0]
    assert "identity_subscribers" in executed_sql


@pytest.mark.asyncio
async def test_order_status_404_for_malformed_order_id():
    """P2: a non-UUID order_id is rejected as 404 before hitting the %s::uuid cast."""
    app = _make_app(order_row=("CREATED", UPDATED_AT, SUBSCRIBER_UUID, MSISDN))
    r = await _get("/api/v1/subscriber/orders/not-a-uuid/status", app)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_active_order_returns_200_null_when_no_order():
    """Return 200 + null fields when the subscriber has no active order (D7).

    A 404 would force the UI into an error page; an empty state is correct.
    """
    app = _make_app()  # no active_row configured
    r = await _get("/api/v1/subscriber/orders/active", app)
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["order_id"] is None
    assert body["data"]["status"] is None
    assert body["data"]["updated_at"] is None


@pytest.mark.asyncio
async def test_active_order_401_when_phone_claim_missing():
    """P1: the active-order endpoint requires phone_number claim (resolver uses it)."""
    from main import create_app

    db = FakeDB({})
    jwt = FakeJWTValidator({"sub": SUBSCRIBER_UUID, "cognito:groups": ["subscriber"]})  # no phone_number claim
    app = create_app(db_adapter=db, jwt_validator=jwt)
    r = await _get("/api/v1/subscriber/orders/active", app)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_order_status_401_when_phone_claim_missing():
    """P1: a valid token lacking 'phone_number' yields 401 (resolver cannot find subscriber)."""
    from main import create_app

    row = ("CREATED", UPDATED_AT, SUBSCRIBER_UUID, MSISDN)
    db = FakeDB({ORDER_UUID: row})
    jwt = FakeJWTValidator({"sub": SUBSCRIBER_UUID, "cognito:groups": ["subscriber"]})  # no phone_number claim
    app = create_app(db_adapter=db, jwt_validator=jwt)
    r = await _get(f"/api/v1/subscriber/orders/{ORDER_UUID}/status", app)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
