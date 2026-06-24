"""Unit tests for DATA_NUDGE consumer (Story 4.1, Task 6)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_get_active_plan_data_quota_returns_quota() -> None:
    """get_active_plan_data_quota returns (data_mb_used, data_limit_mb) for active plan."""
    from db.billing.queries import get_active_plan_data_quota

    # Mock DB connection
    conn = AsyncMock()

    # Mock plan query (returns active subscription with data_limit_mb)
    plan_result = MagicMock()
    plan_result.__iter__ = lambda self: iter(["sub-id", 100, "2024-01-01", "2024-12-31"])

    # Mock usage query (returns SUM(volume_mb))
    usage_result = MagicMock()
    usage_result.fetchone = AsyncMock(return_value=(95.0,))

    conn.execute = AsyncMock(side_effect=[plan_result, usage_result])

    result = await get_active_plan_data_quota(conn, "sub-123")

    assert result == (95.0, 100)


@pytest.mark.asyncio
async def test_get_active_plan_data_quota_returns_none_for_no_subscription() -> None:
    """get_active_plan_data_quota returns None when no active subscription."""
    from db.billing.queries import get_active_plan_data_quota

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=MagicMock(fetchone=AsyncMock(return_value=None)))

    result = await get_active_plan_data_quota(conn, "sub-123")

    assert result is None


@pytest.mark.asyncio
async def test_get_active_plan_data_quota_returns_none_for_unlimited_plan() -> None:
    """get_active_plan_data_quota returns None for unlimited data plans (data_limit_mb=0)."""
    from db.billing.queries import get_active_plan_data_quota

    conn = AsyncMock()
    plan_result = MagicMock()
    plan_result.__iter__ = lambda self: iter(["sub-id", 0, "2024-01-01", "2024-12-31"])
    conn.execute = AsyncMock(return_value=plan_result)

    result = await get_active_plan_data_quota(conn, "sub-123")

    assert result is None
