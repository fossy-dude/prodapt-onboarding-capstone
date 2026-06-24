"""Unit tests for recharge tools (Story 5.6 AC #1, #2, #4).

Tests the `list_plans` and `recharge_flow` Support Agent tools with mocked
database calls to ensure:
- `list_plans` returns top 3 cheapest active plans
- `recharge_flow` with no payment method returns `no_payment_method` status
- `recharge_flow` with saved payment method returns deeplink URL
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agents.support.tools import SUPPORT_TOOLS, set_support_adapters

_SUBSCRIBER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PLAN_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    """Fake cursor that returns pre-programmed rows."""

    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    async def fetchall(self) -> list[tuple]:
        return self._rows

    async def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Fake connection that returns scripted results."""

    def __init__(self, plans_rows: list[tuple] | None = None, payment_row: tuple | None = None) -> None:
        self._plans_rows = plans_rows or []
        self._payment_row = payment_row
        self._call_count = 0

    async def execute(self, sql: str, params=None):
        self._call_count += 1
        if "plans_plans" in sql:
            # Extract LIMIT parameter if present
            limit = None
            if params and len(params) > 0:
                limit = params[0]
            if limit is not None and isinstance(limit, int):
                return _FakeCursor(rows=self._plans_rows[:limit])
            return _FakeCursor(rows=self._plans_rows)
        elif "recharge_payment_methods" in sql:
            return _FakeCursor(rows=[self._payment_row] if self._payment_row else [])
        return _FakeCursor(rows=[])


class FakeDb:
    """Fake DB adapter for tool testing."""

    def __init__(self, plans_rows: list[tuple] | None = None, payment_row: tuple | None = None) -> None:
        self._plans_rows = plans_rows or []
        self._payment_row = payment_row

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(plans_rows=self._plans_rows, payment_row=self._payment_row)

    async def ping(self) -> bool:
        return True


class FakeCache:
    """Fake cache adapter (not used by recharge tools but required by set_support_adapters)."""

    async def ping(self) -> bool:
        return True


def _plan_rows(count: int = 3) -> list[tuple]:
    """Generate fake plan rows ordered by price ascending."""
    return [
        (
            uuid4(),  # id
            f"Plan {i + 1}",  # plan_name
            (i + 1) * 10000,  # price_paise (₹10, ₹20, ₹30...)
            10240 * (i + 1),  # data_limit_mb
            600 * (i + 1),  # voice_minutes
            100 * (i + 1),  # sms_count
        )
        for i in range(count)
    ]


def _get_list_plans_tool():
    """Get the list_plans tool from SUPPORT_TOOLS."""
    for tool in SUPPORT_TOOLS:
        if tool.name == "list_plans":
            return tool
    raise ValueError("list_plans tool not found in SUPPORT_TOOLS")


def _get_recharge_flow_tool():
    """Get the recharge_flow tool from SUPPORT_TOOLS."""
    for tool in SUPPORT_TOOLS:
        if tool.name == "recharge_flow":
            return tool
    raise ValueError("recharge_flow tool not found in SUPPORT_TOOLS")


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_tools():
    """Set up support tools with fake adapters before each test."""
    set_support_adapters(cache=FakeCache(), db=FakeDb())
    yield
    set_support_adapters(cache=None, db=None)


# ── list_plans tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_plans_returns_top_3_cheapest_plans():
    """AC #1: list_plans returns top 3 cheapest active plans ordered by price."""
    db = FakeDb(plans_rows=_plan_rows(count=5))
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_list_plans_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "top_n": 3})

    assert "plans" in result
    plans = result["plans"]
    assert len(plans) == 3

    # Verify ordering: cheapest first
    for i, plan in enumerate(plans):
        assert "plan_id" in plan
        assert "name" in plan
        assert "price_paise" in plan
        assert "price_inr" in plan
        assert "data_limit_mb" in plan
        assert "voice_minutes" in plan
        assert "sms_count" in plan

        # Verify price_inr format (₹X.XX)
        assert plan["price_inr"].startswith("₹")
        assert "," not in plan["price_inr"]  # No comma separators

        # Verify ascending price order (if more than 1 plan)
        if i > 0:
            assert plans[i - 1]["price_paise"] <= plan["price_paise"]


@pytest.mark.asyncio
async def test_list_plans_default_top_n_is_3():
    """Default top_n parameter is 3."""
    db = FakeDb(plans_rows=_plan_rows(count=5))
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_list_plans_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID})

    assert len(result["plans"]) == 3


@pytest.mark.asyncio
async def test_list_plans_respects_top_n_parameter():
    """top_n parameter limits returned plans."""
    db = FakeDb(plans_rows=_plan_rows(count=10))
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_list_plans_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "top_n": 5})

    assert len(result["plans"]) == 5


@pytest.mark.asyncio
async def test_list_plans_returns_empty_when_no_plans():
    """Empty plans table returns empty list."""
    db = FakeDb(plans_rows=[])
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_list_plans_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "top_n": 3})

    assert "plans" in result
    assert len(result["plans"]) == 0


@pytest.mark.asyncio
async def test_list_plans_handles_null_unlimited_quotas():
    """Plans with unlimited quotas (NULL values) are handled correctly."""
    unlimited_plan = (
        uuid4(),
        "Unlimited Plan",
        50000,  # ₹500
        None,  # data_limit_mb (unlimited)
        None,  # voice_minutes (unlimited)
        None,  # sms_count (unlimited)
    )
    db = FakeDb(plans_rows=[unlimited_plan])
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_list_plans_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "top_n": 3})

    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["data_limit_mb"] is None
    assert plan["voice_minutes"] is None
    assert plan["sms_count"] is None
    assert plan["price_inr"] == "₹500.00"


# ── recharge_flow tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recharge_flow_no_payment_method_returns_error_status():
    """AC #4: No saved payment method returns no_payment_method status."""
    # No payment row
    db = FakeDb(plans_rows=[], payment_row=None)
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_recharge_flow_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": _PLAN_ID})

    assert result["status"] == "no_payment_method"
    assert result["url"] is None
    assert "saved payment method" in result["message"].lower()
    assert "Settings > Payment Methods" in result["message"]


@pytest.mark.asyncio
async def test_recharge_flow_with_payment_method_returns_deeplink():
    """AC #2: Saved payment method returns deeplink URL."""
    payment_row = ("card", "4242")  # method_type, last_four
    db = FakeDb(plans_rows=[], payment_row=payment_row)
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_recharge_flow_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": _PLAN_ID})

    assert result["status"] == "deeplink"
    assert result["url"] == f"/subscriber/recharge?plan={_PLAN_ID}"
    assert "complete your recharge" in result["message"].lower()
    assert "pre-selected" in result["message"].lower()
    assert f"/subscriber/recharge?plan={_PLAN_ID}" in result["message"]


@pytest.mark.asyncio
async def test_recharge_flow_includes_correct_plan_id_in_deeplink():
    """Deeplink includes the correct plan_id parameter."""
    custom_plan_id = "cccccccc-cccc-4cccc-8cccccccccccc"
    payment_row = ("upi", None)  # UPI method with no last_four
    db = FakeDb(plans_rows=[], payment_row=payment_row)
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_recharge_flow_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": custom_plan_id})

    assert result["status"] == "deeplink"
    assert result["url"] == f"/subscriber/recharge?plan={custom_plan_id}"
    assert custom_plan_id in result["message"]


@pytest.mark.asyncio
async def test_recharge_flow_handles_different_payment_method_types():
    """Handles different payment method types (card, upi, netbanking, wallet)."""
    for method_type in ["card", "upi", "netbanking", "wallet"]:
        payment_row = (method_type, "1234")
        db = FakeDb(plans_rows=[], payment_row=payment_row)
        set_support_adapters(cache=FakeCache(), db=db)

        tool = _get_recharge_flow_tool()
        result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": _PLAN_ID})

        assert result["status"] == "deeplink"
        assert result["url"] == f"/subscriber/recharge?plan={_PLAN_ID}"


@pytest.mark.asyncio
async def test_recharge_flow_upi_without_last_four():
    """UPI payment methods may have NULL last_four."""
    payment_row = ("upi", None)
    db = FakeDb(plans_rows=[], payment_row=payment_row)
    set_support_adapters(cache=FakeCache(), db=db)

    tool = _get_recharge_flow_tool()
    result = await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": _PLAN_ID})

    assert result["status"] == "deeplink"
    assert result["url"] is not None


# ── Error handling ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_plans_raises_runtime_error_when_db_not_initialized():
    """Tools raise RuntimeError when DB adapter is not set."""
    set_support_adapters(cache=None, db=None)

    tool = _get_list_plans_tool()
    with pytest.raises(RuntimeError, match="Support tools not initialised"):
        await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "top_n": 3})


@pytest.mark.asyncio
async def test_recharge_flow_raises_runtime_error_when_db_not_initialized():
    """Tools raise RuntimeError when DB adapter is not set."""
    set_support_adapters(cache=None, db=None)

    tool = _get_recharge_flow_tool()
    with pytest.raises(RuntimeError, match="Support tools not initialised"):
        await tool.ainvoke({"subscriber_id": _SUBSCRIBER_ID, "plan_id": _PLAN_ID})
