"""Unit tests for USSD session handler and menu router (Story 4.4).

Tests:
- Root menu text exact match (AC #3)
- Balance option reads Valkey key (AC #4)
- Plan option returns name + expiry + remaining (AC #5)
- Exit at root deletes session (AC #9)
- Exit at sub-menu returns root menu (AC #9)
- Unknown MSISDN returns error text (AC #10)
- Session HASH saved with TTL=1800 on every request (AC #1)
- recharge_confirm "1" triggers recharge with correct IDs (AC #7)
- Response Content-Type is text/plain (AC #2)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MSISDN = "919876543210"
_SUB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SESSION_ID = "sess-0001"
_PLAN_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_PM_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


# ---------------------------------------------------------------------------
# Fake DB helpers
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    async def fetchone(self):
        return self._row

    async def fetchall(self):
        return self._rows


class _FakeConn:
    """Configurable fake psycopg connection."""

    def __init__(
        self,
        *,
        subscriber_row=None,
        balance_row=None,
        plan_sub_row=None,
        available_plans=None,
        pref_rows=None,
        payment_method_row=None,
        plan_by_id_row=None,
    ):
        self._subscriber_row = subscriber_row
        self._balance_row = balance_row
        self._plan_sub_row = plan_sub_row
        self._available_plans = available_plans or []
        self._pref_rows = pref_rows or []
        self._payment_method_row = payment_method_row
        self._plan_by_id_row = plan_by_id_row
        self.execute_calls: list[tuple] = []

    async def execute(self, sql: str, params=None):
        self.execute_calls.append((sql, params))
        sql_lower = sql.lower()

        if "identity_subscribers" in sql_lower:
            return _FakeCursor(row=self._subscriber_row)

        if "billing_wallet_balances" in sql_lower and "select" in sql_lower:
            return _FakeCursor(row=self._balance_row)

        if "plans_subscriptions" in sql_lower and "plans_plans" in sql_lower and "select" in sql_lower:
            if self._plan_sub_row is not None:
                return _FakeCursor(row=self._plan_sub_row)
            return _FakeCursor(row=None)

        if "plans_plans" in sql_lower and "select" in sql_lower and "is_active" in sql_lower:
            if "limit %s" in sql_lower:
                return _FakeCursor(rows=self._available_plans)
            if self._plan_by_id_row is not None:
                return _FakeCursor(row=self._plan_by_id_row)
            return _FakeCursor(row=None)

        if "notifications_preferences" in sql_lower and "select" in sql_lower:
            return _FakeCursor(rows=self._pref_rows)

        if "recharge_payment_methods" in sql_lower and "select" in sql_lower:
            return _FakeCursor(row=self._payment_method_row)

        # INSERT / UPDATE / UPSERT — return cursor with no rows
        return _FakeCursor()


class _FakeDb:
    """Fake DB adapter with configurable connection data."""

    def __init__(self, conn: _FakeConn | None = None):
        self._conn = conn or _FakeConn(subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN))

    @asynccontextmanager
    async def transaction(self):
        yield self._conn

    async def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fake cache
# ---------------------------------------------------------------------------


class _FakeCache:
    """Fake Valkey cache tracking hset / hgetall / delete calls."""

    def __init__(self, session_data: dict[str, str] | None = None):
        self._session: dict[str, str] = session_data or {}
        self._str_store: dict[str, str] = {}
        self.hset_calls: list[tuple] = []
        self.delete_calls: list[str] = []
        self.incr_balance_calls: list[tuple] = []

    async def hgetall(self, key: str) -> dict[str, str]:
        if key.startswith("session:"):
            return dict(self._session)
        return {}

    async def hset(self, key: str, mapping: dict[str, str], *, ex: int | None = None) -> None:
        self.hset_calls.append((key, mapping, ex))
        self._session = dict(mapping)

    async def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        self._session = {}

    async def get_str(self, key: str) -> str | None:
        return self._str_store.get(key)

    async def set_str(self, key: str, value: str, ex: int) -> None:
        self._str_store[key] = value

    async def ping(self) -> bool:
        return True

    async def set_balance(self, msisdn: str, paise: int) -> None:
        self._str_store[f"balance:{msisdn}"] = str(paise)

    async def get_balance(self, msisdn: str) -> int | None:
        raw = self._str_store.get(f"balance:{msisdn}")
        return int(raw) if raw is not None else None

    async def incr_balance(self, msisdn: str, delta_paise: int) -> int:
        self.incr_balance_calls.append((msisdn, delta_paise))
        current = int(self._str_store.get(f"balance:{msisdn}", "0"))
        new_val = current + delta_paise
        self._str_store[f"balance:{msisdn}"] = str(new_val)
        return new_val

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        current = int(self._str_store.get(key, "0")) + 1
        self._str_store[key] = str(current)
        return current

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(db=None, cache=None):
    from core.auth import FakeJWTValidator
    from main import create_app

    return create_app(
        db_adapter=db or _FakeDb(),
        cache_adapter=cache or _FakeCache(),
        jwt_validator=FakeJWTValidator(payload={"sub": _SUB_ID, "cognito:groups": ["subscriber"]}),
    )


async def _post(app, body: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/v1/ussd/callback", json=body)


def _req(button: str = "", session_id: str = _SESSION_ID) -> dict:
    return {
        "msisdn": _MSISDN,
        "session_id": session_id,
        "button_pressed": button,
        "ussd_string": "",
    }


# ---------------------------------------------------------------------------
# AC #2: Content-Type must be text/plain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_content_type_is_text_plain():
    """USSD callback always returns text/plain (AC #2)."""
    app = _make_app()
    resp = await _post(app, _req())
    assert "text/plain" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# AC #3: Root menu text exact match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_session_shows_root_menu():
    """New session (empty Valkey HASH) returns exact root menu text (AC #3)."""
    app = _make_app()
    resp = await _post(app, _req(button=""))
    assert resp.status_code == 200
    assert resp.text == "Welcome\n1. Balance\n2. My Plan\n3. Recharge\n4. Notifications\n0. Exit"


# ---------------------------------------------------------------------------
# AC #4: Balance option
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_balance_option_reads_valkey():
    """Button '1' at root reads balance from Valkey and formats as Rs.X.XX (AC #4)."""
    cache = _FakeCache()
    cache._str_store["balance:919876543210"] = "12345"  # 123.45 INR
    app = _make_app(cache=cache)
    resp = await _post(app, _req(button="1"))
    assert resp.status_code == 200
    assert "Rs.123.45" in resp.text
    assert "0. Back" in resp.text


@pytest.mark.asyncio
async def test_balance_falls_back_to_db_on_cold_cache():
    """Balance falls back to billing_wallet_balances when Valkey key absent (AC #4)."""
    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        balance_row=(9900,),
    )
    app = _make_app(db=_FakeDb(conn))
    resp = await _post(app, _req(button="1"))
    assert resp.status_code == 200
    assert "Rs.99.00" in resp.text


# ---------------------------------------------------------------------------
# AC #5: My Plan option
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_option_returns_plan_details():
    """Button '2' at root returns plan name, expiry and allowances (AC #5)."""
    end_date = datetime(2026, 12, 31, tzinfo=UTC)
    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        plan_sub_row=("UltraData", end_date, 10240, 300, 100),
    )
    app = _make_app(db=_FakeDb(conn))
    resp = await _post(app, _req(button="2"))
    assert resp.status_code == 200
    assert "UltraData" in resp.text
    assert "31 Dec 2026" in resp.text
    assert "10240 MB" in resp.text


# ---------------------------------------------------------------------------
# AC #9: Exit behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_at_root_returns_goodbye_and_deletes_session():
    """Button '0' at root returns goodbye text and deletes session key (AC #9)."""
    cache = _FakeCache()
    app = _make_app(cache=cache)
    resp = await _post(app, _req(button="0"))
    assert resp.status_code == 200
    assert resp.text == "Thank you. Goodbye."
    assert f"session:{_SESSION_ID}" in cache.delete_calls


@pytest.mark.asyncio
async def test_exit_at_balance_returns_root_menu():
    """Button '0' at balance sub-menu returns root menu (AC #9)."""
    cache = _FakeCache(session_data={"menu_state": "balance", "subscriber_id": _SUB_ID})
    app = _make_app(cache=cache)
    resp = await _post(app, _req(button="0"))
    assert resp.status_code == 200
    assert "Welcome" in resp.text
    assert "1. Balance" in resp.text


@pytest.mark.asyncio
async def test_exit_at_plan_returns_root_menu():
    """Button '0' at plan sub-menu returns root menu (AC #9)."""
    cache = _FakeCache(session_data={"menu_state": "plan", "subscriber_id": _SUB_ID})
    app = _make_app(cache=cache)
    resp = await _post(app, _req(button="0"))
    assert resp.status_code == 200
    assert "Welcome" in resp.text


@pytest.mark.asyncio
async def test_exit_at_notifications_returns_root_menu():
    """Button '0' at notifications sub-menu returns root menu (AC #9)."""
    cache = _FakeCache(session_data={"menu_state": "notifications", "subscriber_id": _SUB_ID})
    app = _make_app(cache=cache)
    resp = await _post(app, _req(button="0"))
    assert resp.status_code == 200
    assert "Welcome" in resp.text


# ---------------------------------------------------------------------------
# AC #10: Unknown MSISDN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_msisdn_returns_error_text():
    """Unknown MSISDN returns error text without crash (AC #10)."""
    conn = _FakeConn(subscriber_row=None)
    app = _make_app(db=_FakeDb(conn))
    resp = await _post(app, _req())
    assert resp.status_code == 200
    assert "Unknown subscriber" in resp.text
    assert "0. Exit" in resp.text


# ---------------------------------------------------------------------------
# AC #1: Session HASH saved with TTL=1800 on every request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_saved_with_ttl_1800():
    """Session HASH is written to Valkey with TTL=1800 on every request (AC #1)."""
    cache = _FakeCache()
    app = _make_app(cache=cache)
    await _post(app, _req())
    assert len(cache.hset_calls) == 1
    key, _mapping, ex = cache.hset_calls[0]
    assert key == f"session:{_SESSION_ID}"
    assert ex == 1800


# ---------------------------------------------------------------------------
# AC #7: Recharge confirm calls recharge commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_confirm_calls_recharge_commands():
    """Button '1' in recharge_confirm state triggers recharge with correct IDs (AC #7)."""
    plan_by_id_row = (uuid.UUID(_PLAN_ID), "Test Plan", 29900, 2048, 100, 50)
    pm_row = (uuid.UUID(_PM_ID), "card", "1234")

    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        plan_by_id_row=plan_by_id_row,
        payment_method_row=pm_row,
    )

    # Patch create_recharge_order and complete_recharge_transaction
    order_mock = AsyncMock(
        return_value={
            "id": uuid.UUID(_PLAN_ID),
            "subscriber_id": uuid.UUID(_SUB_ID),
            "plan_id": uuid.UUID(_PLAN_ID),
            "amount_paise": 29900,
            "status": "pending",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    result_mock = AsyncMock(
        return_value={
            "transaction_id": uuid.UUID(_PLAN_ID),
            "new_balance_paise": 50000,
            "plan_activation_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "msisdn": _MSISDN,
        }
    )

    import routers.ussd as ussd_module

    original_create = ussd_module.create_recharge_order
    original_complete = ussd_module.complete_recharge_transaction
    ussd_module.create_recharge_order = order_mock
    ussd_module.complete_recharge_transaction = result_mock

    try:
        cache = _FakeCache(
            session_data={
                "menu_state": "recharge_confirm",
                "subscriber_id": _SUB_ID,
                "selected_plan_id": _PLAN_ID,
                "plan_ids": _PLAN_ID,
            }
        )
        app = _make_app(db=_FakeDb(conn), cache=cache)
        resp = await _post(app, _req(button="1"))
    finally:
        ussd_module.create_recharge_order = original_create
        ussd_module.complete_recharge_transaction = original_complete

    assert resp.status_code == 200
    assert "Recharge successful" in resp.text
    order_mock.assert_awaited_once()
    result_mock.assert_awaited_once()
    call_kwargs = order_mock.call_args
    assert str(call_kwargs.kwargs["subscriber_id"]) == _SUB_ID
    assert str(call_kwargs.kwargs["plan_id"]) == _PLAN_ID
    assert str(call_kwargs.kwargs["payment_method_id"]) == _PM_ID


# ---------------------------------------------------------------------------
# Recharge: no saved payment method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_no_payment_method_returns_error():
    """Recharge confirm with no payment method returns error text."""
    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        payment_method_row=None,
    )
    cache = _FakeCache(
        session_data={
            "menu_state": "recharge_confirm",
            "subscriber_id": _SUB_ID,
            "selected_plan_id": _PLAN_ID,
            "plan_ids": _PLAN_ID,
        }
    )
    app = _make_app(db=_FakeDb(conn), cache=cache)
    resp = await _post(app, _req(button="1"))
    assert resp.status_code == 200
    assert "No saved payment method" in resp.text


# ---------------------------------------------------------------------------
# Recharge select: shows plan list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_select_shows_plan_list():
    """Button '3' at root shows numbered plan list (AC #6)."""
    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        available_plans=[
            (uuid.UUID(_PLAN_ID), "Basic", 9900, 512, 60, 50),
        ],
    )
    app = _make_app(db=_FakeDb(conn))
    resp = await _post(app, _req(button="3"))
    assert resp.status_code == 200
    assert "Basic" in resp.text
    assert "1." in resp.text


# ---------------------------------------------------------------------------
# Notifications: toggle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notifications_menu_shows_opt_in_status():
    """Button '4' at root shows current notification opt-in status (AC #8)."""

    class _FakeRow:
        def __init__(self, notification_type, is_enabled):
            self._d = {"notification_type": notification_type, "is_enabled": is_enabled}

        def __getitem__(self, k):
            return self._d[k]

        def keys(self):
            return self._d.keys()

    conn = _FakeConn(
        subscriber_row=(uuid.UUID(_SUB_ID), _MSISDN),
        pref_rows=[
            _FakeRow("LOW_BALANCE", True),
            _FakeRow("BALANCE_DEPLETED", False),
        ],
    )
    app = _make_app(db=_FakeDb(conn))
    resp = await _post(app, _req(button="4"))
    assert resp.status_code == 200
    assert "Notifications" in resp.text
    assert "Low Balance" in resp.text
