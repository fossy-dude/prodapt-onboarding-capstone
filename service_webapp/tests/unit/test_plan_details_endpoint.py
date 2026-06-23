"""Unit tests for GET /api/v1/subscriber/plan (Story 3.4 AC #1, #2).

Returns the active plan subscription joined to its plan: name, validity expiry,
validity days, days remaining, and quotas (data_gb / voice_minutes / sms_count).
Remaining *allowances* come from this endpoint; used-vs-allowance is composed on
the frontend from GET /usage (Story 3.2) — usage is not re-aggregated here.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_MSISDN = "919876543210"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, row: tuple | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Returns a scripted active-plan row (plans_subscriptions JOIN plans_plans)."""

    def __init__(self, plan_row: tuple | None) -> None:
        self._plan_row = plan_row

    async def execute(self, sql: str, params=None):
        return _FakeCursor(row=self._plan_row)


class FakeDb:
    def __init__(self, plan_row: tuple | None = None) -> None:
        self._plan_row = plan_row

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(plan_row=self._plan_row)

    async def ping(self) -> bool:
        return True


def _plan_row(
    *,
    end_date: datetime | None = None,
    validity_days: int = 28,
    data_limit_mb: int | None = 10240,
    voice_minutes: int | None = 600,
    sms_count: int | None = 100,
) -> tuple:
    return (
        uuid4(),  # plan_id
        "Unlimited 5G",  # plan_name
        end_date if end_date is not None else datetime.now(UTC) + timedelta(days=5),
        validity_days,
        data_limit_mb,
        voice_minutes,
        sms_count,
    )


def _sub_payload(sub_id: str = _SUB_A, groups: list[str] | None = None) -> dict:
    return {"sub": sub_id, "cognito:groups": groups or ["subscriber"], "phone_number": _MSISDN}


def _make_app(*, db: FakeDb | None = None, jwt_payload: dict | None = None, jwt_fail: str | None = None):
    from main import create_app

    return create_app(
        db_adapter=db or FakeDb(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload(), fail=jwt_fail),
    )


# ── /plan tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_returns_active_plan_and_quotas():
    """AC #1: plan name, validity expiry, quotas; data_gb = data_limit_mb/1024."""
    db = FakeDb(plan_row=_plan_row(data_limit_mb=10240, voice_minutes=600, sms_count=100))
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["plan_name"] == "Unlimited 5G"
    assert d["validity_days"] == 28
    assert d["validity_expiry"] is not None
    assert d["quotas"]["data_gb"] == pytest.approx(10.0, abs=1e-6)
    assert d["quotas"]["voice_minutes"] == 600
    assert d["quotas"]["sms_count"] == 100
    assert "plan_id" in d


@pytest.mark.asyncio
async def test_plan_days_remaining_countdown():
    """AC #2: days_remaining is the countdown to expiry."""
    end = datetime.now(UTC) + timedelta(days=5)
    db = FakeDb(plan_row=_plan_row(end_date=end))
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    days = r.json()["data"]["days_remaining"]
    assert 4 <= days <= 5


@pytest.mark.asyncio
async def test_plan_unlimited_quotas_when_null():
    """Null quota columns → None in quotas (unlimited)."""
    db = FakeDb(plan_row=_plan_row(data_limit_mb=None, voice_minutes=None, sms_count=None))
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    q = r.json()["data"]["quotas"]
    assert q["data_gb"] is None
    assert q["voice_minutes"] is None
    assert q["sms_count"] is None


@pytest.mark.asyncio
async def test_plan_no_active_plan_404():
    """No active subscription → 404."""
    db = FakeDb(plan_row=None)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plan_no_token_401():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_plan_wrong_role_403():
    app = _make_app(jwt_payload=_sub_payload(groups=["ops"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/plan", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
