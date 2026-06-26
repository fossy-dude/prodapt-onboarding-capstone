"""Tests for GET /api/v1/subscriber/transactions?type=FAILED (Story 3.7).

?type=FAILED reads recharge_orders WHERE status='failed' (NOT billing_transactions).
Default (no type) continues to read billing_transactions (3-3 shape).
With FR-14 simulated-success payment, the failed list is typically empty in MVP.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


class RefundTestContext:
    def __init__(
        self,
        client: AsyncClient,
        mock_conn: AsyncMock,
        test_sub: str,
    ) -> None:
        self.client = client
        self.mock_conn = mock_conn
        self.test_sub = test_sub
        self.auth_headers = {"Authorization": "Bearer fake-token"}

    async def get(self, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers)
        return await self.client.get(path, headers=headers, **kwargs)


@pytest.fixture
async def refund_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RefundTestContext]:
    import routers.balance as balance_module
    from core.auth import FakeJWTValidator
    from main import create_app

    test_sub = str(uuid.uuid4())
    test_msisdn = "911234567890"
    mock_jwt_payload = {"sub": test_sub, "cognito:groups": ["subscriber"], "phone_number": test_msisdn}

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_conn
    mock_db = AsyncMock()
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    # Patch the resolver to return the test subscriber UUID
    async def _fake_resolve_subscriber_id(conn, jwt_payload):
        return test_sub

    monkeypatch.setattr(balance_module, "resolve_subscriber_id", _fake_resolve_subscriber_id)

    jwt_validator = FakeJWTValidator(payload=mock_jwt_payload)
    application = create_app()
    application.state.db_adapter = mock_db
    application.state.cache_adapter = AsyncMock()
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield RefundTestContext(ac, mock_conn, test_sub)

    application.dependency_overrides.clear()


def _failed_row(
    subscriber_id: str,
    *,
    plan_name: str = "Basic Plan",
    amount_paise: int = 9900,
    failure_reason: str | None = "Payment gateway timeout",
) -> dict:
    return {
        "transaction_id": str(uuid.uuid4()),
        "plan_attempted": plan_name,
        "amount_paise": amount_paise,
        "failure_reason": failure_reason,
        "created_at": datetime(2026, 6, 24, 10, 0, 0, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_failed_type_returns_failed_recharge_orders(refund_client: RefundTestContext) -> None:
    """?type=FAILED → 200, returns failed recharge_orders shape (plan_attempted, failure_reason)."""
    rows = [
        _failed_row(refund_client.test_sub),
        _failed_row(refund_client.test_sub, plan_name="Premium Plan", failure_reason=None),
    ]

    with patch("routers.balance.get_failed_orders", return_value=rows):
        response = await refund_client.get("/api/v1/subscriber/transactions?type=FAILED")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert data[0]["plan_attempted"] == "Basic Plan"
    assert data[0]["failure_reason"] == "Payment gateway timeout"
    assert data[1]["failure_reason"] is None
    assert "transaction_id" in data[0]
    assert "amount_paise" in data[0]
    assert "created_at" in data[0]


@pytest.mark.asyncio
async def test_failed_type_empty_list_when_no_failures(refund_client: RefundTestContext) -> None:
    """MVP: simulated-success payment never fails → empty list returned."""
    with patch("routers.balance.get_failed_orders", return_value=[]):
        response = await refund_client.get("/api/v1/subscriber/transactions?type=FAILED")

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_default_type_still_reads_billing_transactions(refund_client: RefundTestContext) -> None:
    """Default (no type param) still hits billing_transactions — 3-3 shape preserved."""
    refund_client.mock_conn.execute.return_value.fetchall.return_value = []

    with patch("routers.balance.get_transactions_page", return_value=[]) as mock_txn:
        response = await refund_client.get("/api/v1/subscriber/transactions")

    assert response.status_code == 200
    mock_txn.assert_called_once()


@pytest.mark.asyncio
async def test_failed_type_401_unauthenticated(refund_client: RefundTestContext) -> None:
    """No auth header → 401."""
    response = await refund_client.client.get("/api/v1/subscriber/transactions?type=FAILED")
    assert response.status_code == 401
