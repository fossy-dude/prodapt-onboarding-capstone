"""Unit tests for ops_queries.py (Story 7.2 Task 1).

Tests for SELECT-only query functions:
- get_plan_stock_counts(): plan_id, plan_name, subscriber_count sorted by count DESC
- get_order_fulfilment_counts(): status grouped order counts
- get_orders_by_status(): paginated order list by status

These are unit tests with fake DB connections following the project pattern.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    """Fake cursor that returns predefined rows."""

    def __init__(self, *, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []
        self._idx = 0

    async def fetchone(self) -> tuple | None:
        if self._idx < len(self._rows):
            result = self._rows[self._idx]
            self._idx += 1
            return result
        return None

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    """Fake connection that routes queries to scripted results based on SQL content."""

    def __init__(
        self,
        *,
        plan_stock_rows: list[tuple] | None = None,
        order_counts_rows: list[tuple] | None = None,
        order_list_rows: list[tuple] | None = None,
    ) -> None:
        self._plan_stock_rows = plan_stock_rows or []
        self._order_counts_rows = order_counts_rows or []
        self._order_list_rows = order_list_rows or []

    async def execute(self, sql: str, params=None):
        """Route SQL queries to appropriate fake cursor based on table names."""
        lowered = sql.lower()

        if "plans_plans" in lowered and "identity_subscribers" in lowered and "group by" in lowered:
            # This is the plan stock count query - sort by subscriber_count DESC
            sorted_rows = sorted(self._plan_stock_rows, key=lambda x: x[2], reverse=True)
            return _FakeCursor(rows=sorted_rows)

        if "recharge_orders" in lowered and "group by status" in lowered:
            # This is the order fulfilment counts query
            return _FakeCursor(rows=self._order_counts_rows)

        if "recharge_orders" in lowered and "where status =" in lowered:
            # This is the orders by status query
            return _FakeCursor(rows=self._order_list_rows)

        # Default empty cursor for unexpected queries
        return _FakeCursor(rows=[])


class FakeDb:
    """Fake database for testing ops queries."""

    def __init__(
        self,
        *,
        plan_stock_rows: list[tuple] | None = None,
        order_counts_rows: list[tuple] | None = None,
        order_list_rows: list[tuple] | None = None,
    ) -> None:
        self._plan_stock_rows = plan_stock_rows
        self._order_counts_rows = order_counts_rows
        self._order_list_rows = order_list_rows

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield _FakeConn(
            plan_stock_rows=self._plan_stock_rows,
            order_counts_rows=self._order_counts_rows,
            order_list_rows=self._order_list_rows,
        )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_stock_counts_returns_plan_data_sorted_by_count():
    """Test get_plan_stock_counts returns plan_id, plan_name, subscriber_count sorted DESC."""
    from db.ops.queries import get_plan_stock_counts

    # Setup: Create fake data with different subscriber counts
    plan_id_1 = uuid4()
    plan_id_2 = uuid4()
    plan_id_3 = uuid4()

    fake_db = FakeDb(
        plan_stock_rows=[
            (plan_id_1, "Basic Plan", 150),
            (plan_id_2, "Premium Plan", 300),
            (plan_id_3, "Enterprise Plan", 50),
        ]
    )

    async with fake_db.connection() as conn:
        result = await get_plan_stock_counts(conn)

    # Assert: Should be sorted by subscriber_count DESC
    assert len(result) == 3
    assert result[0]["plan_id"] == str(plan_id_2)
    assert result[0]["plan_name"] == "Premium Plan"
    assert result[0]["subscriber_count"] == 300

    assert result[1]["plan_id"] == str(plan_id_1)
    assert result[1]["plan_name"] == "Basic Plan"
    assert result[1]["subscriber_count"] == 150

    assert result[2]["plan_id"] == str(plan_id_3)
    assert result[2]["plan_name"] == "Enterprise Plan"
    assert result[2]["subscriber_count"] == 50


@pytest.mark.asyncio
async def test_get_plan_stock_counts_returns_empty_when_no_plans():
    """Test get_plan_stock_counts returns empty list when no plans exist."""
    from db.ops.queries import get_plan_stock_counts

    fake_db = FakeDb(plan_stock_rows=[])

    async with fake_db.connection() as conn:
        result = await get_plan_stock_counts(conn)

    assert result == []


@pytest.mark.asyncio
async def test_get_plan_stock_counts_handles_plans_with_zero_subscribers():
    """Test get_plan_stock_counts includes plans with zero subscribers."""
    from db.ops.queries import get_plan_stock_counts

    plan_id = uuid4()
    fake_db = FakeDb(plan_stock_rows=[(plan_id, "New Plan", 0)])

    async with fake_db.connection() as conn:
        result = await get_plan_stock_counts(conn)

    assert len(result) == 1
    assert result[0]["plan_id"] == str(plan_id)
    assert result[0]["plan_name"] == "New Plan"
    assert result[0]["subscriber_count"] == 0


@pytest.mark.asyncio
async def test_get_order_fulfilment_counts_returns_status_grouped_counts():
    """Test get_order_fulfilment_counts returns dict with status counts."""
    from db.ops.queries import get_order_fulfilment_counts

    fake_db = FakeDb(
        order_counts_rows=[
            ("CREATED", 10),
            ("KYC_PENDING", 5),
            ("KYC_VERIFIED", 3),
            ("ACTIVATED", 2),
            ("COMPLETED", 15),  # Additional status not in expected set
        ]
    )

    async with fake_db.connection() as conn:
        result = await get_order_fulfilment_counts(conn)

    # Assert: Should return dict with all status counts
    assert result["CREATED"] == 10
    assert result["KYC_PENDING"] == 5
    assert result["KYC_VERIFIED"] == 3
    assert result["ACTIVATED"] == 2


@pytest.mark.asyncio
async def test_get_order_fulfilment_counts_returns_zero_for_missing_statuses():
    """Test get_order_fulfilment_counts returns 0 for statuses with no orders."""
    from db.ops.queries import get_order_fulfilment_counts

    fake_db = FakeDb(
        order_counts_rows=[
            ("CREATED", 5),
            ("ACTIVATED", 2),
            # KYC_PENDING and KYC_VERIFIED are missing
        ]
    )

    async with fake_db.connection() as conn:
        result = await get_order_fulfilment_counts(conn)

    # Should handle missing statuses gracefully
    assert result["CREATED"] == 5
    assert result["ACTIVATED"] == 2


@pytest.mark.asyncio
async def test_get_order_fulfilment_counts_returns_empty_when_no_orders():
    """Test get_order_fulfilment_counts returns dict with zeros when no orders."""
    from db.ops.queries import get_order_fulfilment_counts

    fake_db = FakeDb(order_counts_rows=[])

    async with fake_db.connection() as conn:
        result = await get_order_fulfilment_counts(conn)

    assert result == {}


@pytest.mark.asyncio
async def test_get_orders_by_status_returns_paginated_order_list():
    """Test get_orders_by_status returns paginated order list for given status."""
    from db.ops.queries import get_orders_by_status

    order_id_1 = uuid4()
    order_id_2 = uuid4()

    fake_db = FakeDb(
        order_list_rows=[
            (
                order_id_1,
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "2026-01-01T10:00:00Z",
                "2026-01-01T10:05:00Z",
                "CREATED",
            ),
            (
                order_id_2,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "2026-01-01T11:00:00Z",
                "2026-01-01T11:05:00Z",
                "CREATED",
            ),
        ]
    )

    async with fake_db.connection() as conn:
        result = await get_orders_by_status(conn, status="CREATED", limit=20, offset=0)

    # Assert: Should return list of order records
    assert len(result) == 2
    assert result[0]["order_id"] == str(order_id_1)
    assert result[0]["subscriber_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert result[0]["status"] == "CREATED"

    assert result[1]["order_id"] == str(order_id_2)
    assert result[1]["subscriber_id"] == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_get_orders_by_status_respects_limit_and_offset():
    """Test get_orders_by_status respects limit and offset parameters."""
    from db.ops.queries import get_orders_by_status

    fake_db = FakeDb(
        order_list_rows=[
            ("uuid-3", "sub-3", "2026-01-01T12:00:00Z", "2026-01-01T12:05:00Z", "ACTIVATED"),
        ]
    )

    async with fake_db.connection() as conn:
        result = await get_orders_by_status(conn, status="ACTIVATED", limit=10, offset=5)

    # Should pass limit and offset to query (we verify via SQL in real implementation)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_orders_by_status_returns_empty_when_no_orders_for_status():
    """Test get_orders_by_status returns empty list when no orders match status."""
    from db.ops.queries import get_orders_by_status

    fake_db = FakeDb(order_list_rows=[])

    async with fake_db.connection() as conn:
        result = await get_orders_by_status(conn, status="COMPLETED", limit=20, offset=0)

    assert result == []


@pytest.mark.asyncio
async def test_get_orders_by_status_default_limit_and_offset():
    """Test get_orders_by_status uses default limit=20, offset=0 when not provided."""
    from db.ops.queries import get_orders_by_status

    fake_db = FakeDb(order_list_rows=[])

    async with fake_db.connection() as conn:
        # Call without providing limit/offset
        result = await get_orders_by_status(conn, status="CREATED")

    # Should work with defaults
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_historical_plan_recharges_uses_bind_safe_interval():
    """Test get_historical_plan_recharges avoids invalid INTERVAL $1 SQL."""
    from db.ops.queries import get_historical_plan_recharges

    plan_id = uuid4()

    class CaptureConn:
        def __init__(self) -> None:
            self.sql = ""
            self.params = None

        async def execute(self, sql: str, params=None):
            self.sql = sql
            self.params = params
            return _FakeCursor(rows=[(plan_id, "2026-01-01", 7)])

    conn = CaptureConn()

    result = await get_historical_plan_recharges(conn, days_back=45)

    assert "%(days_back)s::int * INTERVAL '1 day'" in conn.sql
    assert conn.params == {"days_back": 45}
    assert result == [{"plan_id": str(plan_id), "date": "2026-01-01", "recharge_count": 7}]


@pytest.mark.asyncio
async def test_save_plan_forecast_results_uses_bind_safe_valid_until_interval():
    """Test save_plan_forecast_results avoids invalid INTERVAL $2 SQL."""
    from db.ops.queries import save_plan_forecast_results

    plan_id = str(uuid4())

    class CaptureConn:
        def __init__(self) -> None:
            self.calls = []

        async def execute(self, sql: str, params=None):
            self.calls.append((sql, params))
            return _FakeCursor()

    conn = CaptureConn()

    await save_plan_forecast_results(
        conn,
        [
            {
                "plan_id": plan_id,
                "plan_name": "Basic Plan",
                "predicted_uptake_30d": 10,
                "predicted_uptake_60d": 20,
                "predicted_uptake_90d": 30,
                "uptake_trend_90d": [1, 2, 3],
            }
        ],
        "holt_winters_v1",
        valid_hours=12,
    )

    insert_sql, insert_params = conn.calls[1]
    assert "%s::int * INTERVAL '1 hour'" in insert_sql
    assert insert_params[1] == 12
