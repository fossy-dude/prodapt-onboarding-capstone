"""Unit tests for balance & usage endpoints (Story 3.2 AC #1-#6).

GET /api/v1/subscriber/balance and GET /api/v1/subscriber/usage are exercised
with FakeJWTValidator + in-memory fakes for the Valkey cache and Postgres adapter.
No real infrastructure is required.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_MSISDN = "919876543210"

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_END = _NOW + timedelta(days=28)


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, *, row: tuple | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Routes queries to scripted results based on the SQL table name."""

    def __init__(
        self, *, wallet_row: tuple | None, sub_row: tuple | None, plan_row: tuple | None, usage_row: tuple | None
    ) -> None:
        self._wallet_row = wallet_row
        self._sub_row = sub_row
        self._plan_row = plan_row
        self._usage_row = usage_row

    async def execute(self, sql: str, params=None):
        lowered = sql.lower()
        if "billing_wallet_balances" in lowered:
            return _FakeCursor(row=self._wallet_row)
        if "identity_subscribers" in lowered:
            return _FakeCursor(row=self._sub_row)
        if "plans_subscriptions" in lowered and "plans_plans" in lowered:
            return _FakeCursor(row=self._plan_row)
        if "billing_cdr_events" in lowered:
            return _FakeCursor(row=self._usage_row)
        return _FakeCursor()


class FakeDb:
    def __init__(
        self,
        *,
        wallet_row: tuple | None = (50000, _MSISDN, _NOW, None),
        sub_row: tuple | None = (_SUB_A,),
        plan_row: tuple | None = None,
        usage_row: tuple | None = None,
    ) -> None:
        self._wallet_row = wallet_row
        self._sub_row = sub_row
        self._plan_row = plan_row
        self._usage_row = usage_row

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(
            wallet_row=self._wallet_row,
            sub_row=self._sub_row,
            plan_row=self._plan_row,
            usage_row=self._usage_row,
        )

    async def ping(self) -> bool:
        return True


class FakeCache:
    def __init__(self, balance: int | None = 50000) -> None:
        self._balance = balance
        self.get_calls: list[str] = []

    async def ping(self) -> bool:
        return True

    async def set_str(self, key: str, value: str, ex: int) -> None:
        pass

    async def get_str(self, key: str) -> str | None:
        return None

    async def delete(self, key: str) -> None:
        pass

    async def set_balance(self, msisdn: str, paise: int) -> None:
        pass

    async def get_balance(self, msisdn: str) -> int | None:
        self.get_calls.append(msisdn)
        return self._balance

    async def close(self) -> None:
        pass


def _sub_payload(sub_id: str = _SUB_A, groups: list[str] | None = None) -> dict:
    return {"sub": sub_id, "cognito:groups": groups or ["subscriber"], "phone_number": _MSISDN}


def _make_app(
    *,
    db: FakeDb | None = None,
    cache: FakeCache | None = None,
    jwt_payload: dict | None = None,
    jwt_fail: str | None = None,
):
    from main import create_app

    return create_app(
        db_adapter=db or FakeDb(),
        cache_adapter=cache or FakeCache(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload(), fail=jwt_fail),
    )


# ── /balance tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_balance_returns_paise_and_inr():
    """AC #1: balance_paise returned; balance_inr = ₹500.00 for 50000 paise."""
    app = _make_app(cache=FakeCache(balance=50000))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["balance_paise"] == 50000
    assert data["balance_inr"] == "₹500.00"
    assert data["msisdn_masked"] == "***3210"


@pytest.mark.asyncio
async def test_balance_reads_valkey_first():
    """AC #2: Valkey is queried (cache hit case)."""
    cache = FakeCache(balance=99900)
    app = _make_app(cache=cache)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json()["data"]["balance_paise"] == 99900
    assert cache.get_calls == [_MSISDN]


@pytest.mark.asyncio
async def test_balance_falls_back_to_postgres_on_cache_miss():
    """AC #2: Valkey miss → Postgres fallback value returned."""
    db = FakeDb(wallet_row=(12345, _MSISDN, _NOW, None))
    app = _make_app(db=db, cache=FakeCache(balance=None))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json()["data"]["balance_paise"] == 12345


@pytest.mark.asyncio
async def test_balance_zero_returns_200():
    """AC #3: balance=0 still returns 200 (UI shows banner, not an error)."""
    app = _make_app(cache=FakeCache(balance=0))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json()["data"]["balance_paise"] == 0
    assert r.json()["data"]["balance_inr"] == "₹0.00"


@pytest.mark.asyncio
async def test_balance_no_token_401():
    """Auth matrix: missing token → 401."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_balance_wrong_role_403():
    """Auth matrix: valid token but wrong role → 403."""
    app = _make_app(jwt_payload=_sub_payload(groups=["ops"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_balance_invalid_token_401():
    """Auth matrix: invalid token → 401."""
    app = _make_app(jwt_fail="invalid")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_balance_wallet_not_found_404():
    """Subscriber has no wallet row → 404."""
    db = FakeDb(wallet_row=None)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_balance_subscriber_not_found_404():
    """Token phone number does not resolve to a subscriber → 404."""
    db = FakeDb(sub_row=None)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 404


# ── /usage tests ───────────────────────────────────────────────────────────────

_PLAN_ROW = (
    uuid4(),  # subscription_id
    uuid4(),  # plan_id
    _NOW,  # start_date
    _END,  # end_date
    600,  # voice_minutes_allowance
    10240,  # data_limit_mb_allowance (10 GB)
    100,  # sms_count_allowance
)

_USAGE_ROW = (
    120.5,  # voice_minutes_used
    2048.0,  # data_mb_used
    30,  # sms_count_used
    512.0,  # roaming_mb_used
)


@pytest.mark.asyncio
async def test_usage_returns_per_type_breakdown():
    """AC #4: usage endpoint returns all four types with used + allowance."""
    db = FakeDb(plan_row=_PLAN_ROW, usage_row=_USAGE_ROW)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/usage", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["voice_minutes"]["used"] == pytest.approx(120.5, rel=1e-3)
    assert d["voice_minutes"]["allowance"] == 600.0
    assert d["voice_minutes"]["unlimited"] is False
    assert d["data"]["used"] == pytest.approx(2048.0, rel=1e-3)
    assert d["data_mb"] == pytest.approx(2048.0, rel=1e-3)
    assert d["data_gb"] == pytest.approx(2.0, rel=1e-2)
    assert d["sms"]["used"] == pytest.approx(30.0, rel=1e-3)
    assert d["roaming_mb"]["used"] == pytest.approx(512.0, rel=1e-3)


@pytest.mark.asyncio
async def test_usage_unlimited_when_no_cap():
    """AC #5: null quota → unlimited=True, allowance=None."""
    plan_row_unlimited = (uuid4(), uuid4(), _NOW, _END, None, None, None)
    db = FakeDb(plan_row=plan_row_unlimited, usage_row=_USAGE_ROW)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/usage", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["voice_minutes"]["unlimited"] is True
    assert d["voice_minutes"]["allowance"] is None
    assert d["data"]["unlimited"] is True
    assert d["sms"]["unlimited"] is True


@pytest.mark.asyncio
async def test_usage_no_active_plan_404():
    """No active plan → 404."""
    db = FakeDb(plan_row=None, usage_row=None)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/usage", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_usage_no_token_401():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/usage")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_usage_wrong_role_403():
    app = _make_app(jwt_payload=_sub_payload(groups=["fraud"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/usage", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
