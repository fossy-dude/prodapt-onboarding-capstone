"""API tests for ops dashboard endpoints (Story 7.2 Task 2).

Tests for:
- GET /api/v1/ops/plan-stock (ops role only, returns plan counts)
- GET /api/v1/ops/orders (ops role only, returns order counts or paginated list)
- 401/403 for unauthorized access
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Test constants
_SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SUB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# ── Test Context ─────────────────────────────────────────────────────────────


class OpsTestContext:
    """Holds test fixtures for ops tests."""

    client: AsyncClient
    mock_get_plan_stock_counts: AsyncMock
    mock_get_order_fulfilment_counts: AsyncMock
    mock_get_orders_by_status: AsyncMock
    test_sub: str

    def __init__(
        self,
        client: AsyncClient,
        mock_get_plan_stock_counts: AsyncMock,
        mock_get_order_fulfilment_counts: AsyncMock,
        mock_get_orders_by_status: AsyncMock,
        test_sub: str,
    ) -> None:
        self.client = client
        self.mock_get_plan_stock_counts = mock_get_plan_stock_counts
        self.mock_get_order_fulfilment_counts = mock_get_order_fulfilment_counts
        self.mock_get_orders_by_status = mock_get_orders_by_status
        self.test_sub = test_sub
        self.auth_headers = {"Authorization": "Bearer fake-token"}

    # Make the OpsTestContext behave like the client for convenience
    async def get(self, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers)
        return await self.client.get(path, headers=headers, **kwargs)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def ops_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OpsTestContext]:
    """App with async HTTP client + JWT middleware mocked + DB queries mocked."""
    import routers.ops as ops_module
    from main import create_app

    test_sub = str(uuid4())
    test_msisdn = "919876543210"
    mock_jwt_payload = {
        "sub": test_sub,
        "cognito:groups": ["ops"],
        "phone_number": test_msisdn,
        "username": test_msisdn,
    }

    # Patch the DB query functions at the router module boundary
    mock_get_plan_stock = AsyncMock(return_value=[])
    mock_get_order_counts = AsyncMock(return_value={})
    mock_get_orders_by_status = AsyncMock(return_value=[])
    mock_get_subscriber_id_by_msisdn = AsyncMock(return_value=test_sub)
    monkeypatch.setattr(ops_module, "get_plan_stock_counts", mock_get_plan_stock)
    monkeypatch.setattr(ops_module, "get_order_fulfilment_counts", mock_get_order_counts)
    monkeypatch.setattr(ops_module, "get_orders_by_status", mock_get_orders_by_status)
    monkeypatch.setattr(ops_module, "get_subscriber_id_by_msisdn", mock_get_subscriber_id_by_msisdn)

    # Mock database adapter (for the _db function)
    mock_conn = AsyncMock()
    mock_db = AsyncMock()
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    mock_db.connection = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    jwt_validator = FakeJWTValidator(payload=mock_jwt_payload)

    application = create_app()
    application.dependency_overrides[lambda: jwt_validator] = lambda: jwt_validator
    application.state.db_adapter = mock_db
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield OpsTestContext(
            ac,
            mock_get_plan_stock,
            mock_get_order_counts,
            mock_get_orders_by_status,
            test_sub,
        )

    application.dependency_overrides.clear()


@pytest.fixture
async def subscriber_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """App with async HTTP client + subscriber role JWT (unauthorized for ops)."""
    from main import create_app

    sub_payload = {"sub": _SUB_B, "cognito:groups": ["subscriber"]}
    jwt_validator = FakeJWTValidator(payload=sub_payload)

    application = create_app()
    application.dependency_overrides[lambda: jwt_validator] = lambda: jwt_validator
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    application.dependency_overrides.clear()


# Helper to make authenticated requests
async def _auth_get(client: AsyncClient, path: str) -> Any:
    """Make a GET request with Bearer token authentication."""
    return await client.get(path, headers={"Authorization": "Bearer fake-token"})


@pytest.fixture
async def unauthenticated_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """App with async HTTP client + no JWT (unauthenticated)."""
    from main import create_app

    jwt_validator = FakeJWTValidator(fail="invalid")

    application = create_app()
    application.dependency_overrides[lambda: jwt_validator] = lambda: jwt_validator
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    application.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_stock_with_ops_role_returns_200(ops_client: OpsTestContext) -> None:
    """Test GET /api/v1/ops/plan-stock with ops role returns 200 with plan data."""
    plan_id_1 = uuid4()
    plan_id_2 = uuid4()

    # Setup: Mock query to return plan data
    ops_client.mock_get_plan_stock_counts.return_value = [
        {
            "plan_id": str(plan_id_2),
            "plan_name": "Premium Plan",
            "subscriber_count": 300,
        },
        {
            "plan_id": str(plan_id_1),
            "plan_name": "Basic Plan",
            "subscriber_count": 150,
        },
    ]

    response = await ops_client.get("/api/v1/ops/plan-stock")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    plans = data["data"]
    assert len(plans) == 2
    assert plans[0]["plan_id"] == str(plan_id_2)
    assert plans[0]["plan_name"] == "Premium Plan"
    assert plans[0]["subscriber_count"] == 300


@pytest.mark.asyncio
async def test_get_plan_stock_with_subscriber_role_returns_403(subscriber_client: AsyncClient) -> None:
    """Test GET /api/v1/ops/plan-stock with subscriber role returns 403 Forbidden."""
    resp = await _auth_get(subscriber_client, "/api/v1/ops/plan-stock")

    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_plan_stock_with_no_auth_returns_401(unauthenticated_client: AsyncClient) -> None:
    """Test GET /api/v1/ops/plan-stock with no auth returns 401 Unauthorized."""
    resp = await unauthenticated_client.get("/api/v1/ops/plan-stock")

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_get_orders_without_status_returns_counts(ops_client: OpsTestContext) -> None:
    """Test GET /api/v1/ops/orders without status param returns status counts."""
    # Setup: Mock query to return status counts
    ops_client.mock_get_order_fulfilment_counts.return_value = {
        "CREATED": 10,
        "ACTIVATED": 5,
    }

    response = await ops_client.get("/api/v1/ops/orders")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    counts = data["data"]
    assert counts["CREATED"] == 10
    assert counts["ACTIVATED"] == 5


@pytest.mark.asyncio
async def test_get_orders_with_status_returns_paginated_list(ops_client: OpsTestContext) -> None:
    """Test GET /api/v1/ops/orders?status=CREATED returns paginated order list."""
    order_id_1 = uuid4()

    # Setup: Mock query to return order list
    ops_client.mock_get_orders_by_status.return_value = [
        {
            "order_id": str(order_id_1),
            "subscriber_id": _SUB_A,
            "created_at": "2026-01-01T10:00:00Z",
            "updated_at": "2026-01-01T10:05:00Z",
            "status": "CREATED",
        }
    ]

    response = await ops_client.get("/api/v1/ops/orders?status=CREATED&limit=20&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    orders = data["data"]
    assert len(orders) == 1
    assert orders[0]["order_id"] == str(order_id_1)
    assert orders[0]["status"] == "CREATED"


@pytest.mark.asyncio
async def test_get_orders_with_subscriber_role_returns_403(subscriber_client: AsyncClient) -> None:
    """Test GET /api/v1/ops/orders with subscriber role returns 403 Forbidden."""
    resp = await _auth_get(subscriber_client, "/api/v1/ops/orders")

    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_orders_with_no_auth_returns_401(unauthenticated_client: AsyncClient) -> None:
    """Test GET /api/v1/ops/orders with no auth returns 401 Unauthorized."""
    resp = await unauthenticated_client.get("/api/v1/ops/orders")

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_get_orders_with_limit_offset_params(ops_client: OpsTestContext) -> None:
    """Test GET /api/v1/ops/orders respects limit and offset params."""
    # Setup: Mock query to return order list
    ops_client.mock_get_orders_by_status.return_value = [
        {
            "order_id": str(uuid4()),
            "subscriber_id": _SUB_A,
            "created_at": "2026-01-01T10:00:00Z",
            "updated_at": "2026-01-01T10:05:00Z",
            "status": "ACTIVATED",
        }
    ]

    response = await ops_client.get("/api/v1/ops/orders?status=ACTIVATED&limit=10&offset=5")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    # Should return paginated results
    assert isinstance(data["data"], list)
