"""Unit tests for GET /api/v1/plans (Story 3.4 AC #3, catalogue).

The endpoint is exercised with FakeJWTValidator + an in-memory fake Postgres
adapter that scripts ``plans_plans`` rows. No real infrastructure is required.
The ``is_active`` SQL filter is verified in the integration suite (skipped by
default); these unit tests cover response shape, ``data_gb`` conversion, and the
auth matrix.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_MSISDN = "919876543210"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    """Returns scripted ``plans_plans`` rows."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def execute(self, sql: str, params=None):
        return _FakeCursor(self._rows)


class FakeDb:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(self._rows)

    async def ping(self) -> bool:
        return True


def _plan_row(
    *,
    name: str = "Unlimited 5G",
    price_paise: int = 29900,
    validity_days: int = 28,
    data_limit_mb: int | None = 10240,
    voice_minutes: int | None = 600,
    sms_count: int | None = 100,
) -> tuple:
    """7-column row matching the get_active_plans SELECT order."""
    return (uuid4(), name, price_paise, validity_days, data_limit_mb, voice_minutes, sms_count)


def _sub_payload(groups: list[str] | None = None) -> dict:
    return {
        "sub": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "cognito:groups": groups or ["subscriber"],
        "phone_number": _MSISDN,
    }


def _make_app(*, db: FakeDb | None = None, jwt_payload: dict | None = None, jwt_fail: str | None = None):
    from main import create_app

    return create_app(
        db_adapter=db or FakeDb(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload(), fail=jwt_fail),
    )


# ── /plans tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plans_returns_active_plans():
    """AC #3: catalogue returns active plans with all required fields."""
    db = FakeDb(rows=[_plan_row(name="Unlimited 5G"), _plan_row(name="Talkathon 28")])
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/plans", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"Unlimited 5G", "Talkathon 28"}
    item = items[0]
    assert item["price_paise"] == 29900
    assert item["validity_days"] == 28
    assert "id" in item
    assert item["plan_type"] is None  # V1 has no plan_type column (variance)


@pytest.mark.asyncio
async def test_plans_data_gb_conversion():
    """AC #3: data_gb = round(data_limit_mb/1024, 2); null data_limit_mb → None (unlimited)."""
    rows = [
        _plan_row(name="Data10", data_limit_mb=10240),  # 10 GB
        _plan_row(name="DataHalf", data_limit_mb=5120),  # 5 GB
        _plan_row(name="UnlimitedData", data_limit_mb=None),
    ]
    db = FakeDb(rows=rows)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/plans", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    by_name = {i["name"]: i for i in r.json()["data"]}
    assert by_name["Data10"]["data_gb"] == pytest.approx(10.0, abs=1e-6)
    assert by_name["DataHalf"]["data_gb"] == pytest.approx(5.0, abs=1e-6)
    assert by_name["UnlimitedData"]["data_gb"] is None
    assert by_name["UnlimitedData"]["voice_minutes"] == 600


@pytest.mark.asyncio
async def test_plans_empty_when_no_active():
    """No active plans → empty list (200), not an error."""
    db = FakeDb(rows=[])
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/plans", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_plans_no_token_401():
    """Auth matrix: missing token → 401."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/plans")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_plans_wrong_role_403():
    """Auth matrix: valid token but wrong role → 403."""
    app = _make_app(jwt_payload=_sub_payload(groups=["ops"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/plans", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
