"""API tests for ops dashboard endpoints (Story 7.2 Task 2; Story 7.4 Task 9).

Tests for:
- GET /api/v1/ops/plan-stock (ops role only, returns plan counts)
- GET /api/v1/ops/orders (ops role only, returns order counts or paginated list)
- GET /api/v1/ops/forecasts/plan-demand (ops + marketing roles, returns per-plan forecast)
- 401/403 for unauthorized access
"""

from __future__ import annotations

from datetime import date, timedelta
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


# ── Plan Demand Forecast fixtures ─────────────────────────────────────────────


def _make_forecast_row(plan_id: str, plan_name: str) -> dict:
    return {
        "plan_id": plan_id,
        "plan_name": plan_name,
        "predicted_uptake_30d": 100,
        "predicted_uptake_60d": 200,
        "predicted_uptake_90d": 300,
        "uptake_trend_90d": list(range(90)),
        "model_version": "holt_winters_v1",
        "trained_at": None,
        "valid_until": None,
    }


@pytest.fixture
async def forecast_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OpsTestContext]:
    """App with ops-role JWT + plan demand query functions mocked."""
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

    mock_get_cached = AsyncMock(return_value=[])
    mock_get_historical = AsyncMock(return_value=[])
    mock_save = AsyncMock(return_value=None)
    mock_get_plan_stock = AsyncMock(return_value=[])
    mock_get_order_counts = AsyncMock(return_value={})
    mock_get_orders_by_status = AsyncMock(return_value=[])
    mock_get_subscriber_id = AsyncMock(return_value=test_sub)

    monkeypatch.setattr(ops_module, "get_cached_plan_forecast", mock_get_cached)
    monkeypatch.setattr(ops_module, "get_historical_plan_recharges", mock_get_historical)
    monkeypatch.setattr(ops_module, "save_plan_forecast_results", mock_save)
    monkeypatch.setattr(ops_module, "get_plan_stock_counts", mock_get_plan_stock)
    monkeypatch.setattr(ops_module, "get_order_fulfilment_counts", mock_get_order_counts)
    monkeypatch.setattr(ops_module, "get_orders_by_status", mock_get_orders_by_status)
    monkeypatch.setattr(ops_module, "get_subscriber_id_by_msisdn", mock_get_subscriber_id)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchall=AsyncMock(return_value=[])))
    mock_db = AsyncMock()
    mock_db.connection = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    jwt_validator = FakeJWTValidator(payload=mock_jwt_payload)
    application = create_app()
    application.state.db_adapter = mock_db
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ctx = OpsTestContext(ac, mock_get_plan_stock, mock_get_order_counts, mock_get_orders_by_status, test_sub)
        ctx._mock_get_cached = mock_get_cached  # type: ignore[attr-defined]
        ctx._mock_get_historical = mock_get_historical  # type: ignore[attr-defined]
        yield ctx

    application.dependency_overrides.clear()


@pytest.fixture
async def marketing_forecast_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """App with marketing-role JWT for plan demand endpoint access check."""
    import routers.ops as ops_module
    from main import create_app

    marketing_payload = {"sub": _SUB_A, "cognito:groups": ["marketing"]}
    mock_get_cached = AsyncMock(return_value=[_make_forecast_row(str(uuid4()), "Budget Plan")])
    monkeypatch.setattr(ops_module, "get_cached_plan_forecast", mock_get_cached)
    monkeypatch.setattr(ops_module, "get_historical_plan_recharges", AsyncMock(return_value=[]))
    monkeypatch.setattr(ops_module, "save_plan_forecast_results", AsyncMock())
    monkeypatch.setattr(ops_module, "get_plan_stock_counts", AsyncMock(return_value=[]))
    monkeypatch.setattr(ops_module, "get_order_fulfilment_counts", AsyncMock(return_value={}))
    monkeypatch.setattr(ops_module, "get_orders_by_status", AsyncMock(return_value=[]))
    monkeypatch.setattr(ops_module, "get_subscriber_id_by_msisdn", AsyncMock(return_value=_SUB_A))

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchall=AsyncMock(return_value=[])))
    mock_db = AsyncMock()
    mock_db.connection = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    jwt_validator = FakeJWTValidator(payload=marketing_payload)
    application = create_app()
    application.state.db_adapter = mock_db
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    application.dependency_overrides.clear()


# ── Plan Demand Forecast tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_demand_cache_hit_returns_200(forecast_client: OpsTestContext) -> None:
    """Cached forecast returned immediately without retraining."""
    plan_id = str(uuid4())
    forecast_client._mock_get_cached.return_value = [_make_forecast_row(plan_id, "Basic Plan")]  # type: ignore[attr-defined]

    response = await forecast_client.get("/api/v1/ops/forecasts/plan-demand")

    assert response.status_code == 200
    body = response.json()["data"]
    assert len(body["forecasts"]) == 1
    assert body["forecasts"][0]["plan_id"] == plan_id
    assert body["forecasts"][0]["plan_name"] == "Basic Plan"
    assert body["forecasts"][0]["predicted_uptake_30d"] == 100
    assert body["forecasts"][0]["predicted_uptake_90d"] == 300
    assert len(body["forecasts"][0]["uptake_trend_90d"]) == 90


@pytest.mark.asyncio
async def test_plan_demand_empty_history_returns_empty_forecasts(forecast_client: OpsTestContext) -> None:
    """No historical recharge data → empty forecast list."""
    forecast_client._mock_get_cached.return_value = []  # type: ignore[attr-defined]
    forecast_client._mock_get_historical.return_value = []  # type: ignore[attr-defined]

    response = await forecast_client.get("/api/v1/ops/forecasts/plan-demand")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["forecasts"] == []


@pytest.mark.asyncio
async def test_plan_demand_with_marketing_role_returns_200(marketing_forecast_client: AsyncClient) -> None:
    """Marketing role can access plan demand endpoint."""
    response = await marketing_forecast_client.get(
        "/api/v1/ops/forecasts/plan-demand",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_plan_demand_with_subscriber_role_returns_403(subscriber_client: AsyncClient) -> None:
    """Subscriber role is forbidden from plan demand endpoint."""
    resp = await _auth_get(subscriber_client, "/api/v1/ops/forecasts/plan-demand")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_plan_demand_with_no_auth_returns_401(unauthenticated_client: AsyncClient) -> None:
    """Unauthenticated request returns 401."""
    resp = await unauthenticated_client.get("/api/v1/ops/forecasts/plan-demand")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_plan_demand_cache_not_called_when_force_refresh(forecast_client: OpsTestContext) -> None:
    """force_refresh=true bypasses cached result check."""
    forecast_client._mock_get_cached.return_value = [_make_forecast_row(str(uuid4()), "Plan")]  # type: ignore[attr-defined]
    forecast_client._mock_get_historical.return_value = []  # type: ignore[attr-defined]

    response = await forecast_client.get("/api/v1/ops/forecasts/plan-demand?force_refresh=true")

    assert response.status_code == 200
    forecast_client._mock_get_cached.assert_not_called()  # type: ignore[attr-defined]


# ── Subscriber Growth Forecast fixtures (Story 7.3) ──────────────────────────


def _make_growth_history(active_days: int = 120) -> list[dict]:
    """180-day window with exactly *active_days* non-zero-activation days."""
    today = date.today()
    start = today - timedelta(days=179)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "activations": 10 if i < active_days else 0,
            "churn": 1 if i < active_days else 0,
        }
        for i in range(180)
    ]


def _make_growth_payload() -> dict:
    return {
        "forecast_type": "subscriber_growth",
        "model_version": "gradient_boosting_v1",
        "trained_at": "2026-06-26T10:00:00+00:00",
        "horizon_days": 90,
        "metrics": {
            "mape_activations": 8.0,
            "mape_churn": 12.0,
            "passed_mape_threshold": True,
            "holdout_days": 30,
        },
        "forecasts": [
            {
                "date": "2026-07-01",
                "predicted_activations": 150,
                "predicted_churn": 30,
                "lower_bound_activations": 140,
                "upper_bound_activations": 160,
                "lower_bound_churn": 25,
                "upper_bound_churn": 35,
            }
        ],
    }


class GrowthTestContext:
    """Holds the subscriber-growth mocked dependencies for ops tests."""

    def __init__(
        self,
        client: AsyncClient,
        mock_cached: AsyncMock,
        mock_historical: AsyncMock,
        mock_save: AsyncMock,
        mock_build: MagicMock,
    ) -> None:
        self.client = client
        self.mock_cached = mock_cached
        self.mock_historical = mock_historical
        self.mock_save = mock_save
        self.mock_build = mock_build
        self.auth_headers = {"Authorization": "Bearer fake-token"}

    async def get(self, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers)
        return await self.client.get(path, headers=headers, **kwargs)


@pytest.fixture
async def growth_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[GrowthTestContext]:
    """App with ops-role JWT + subscriber-growth query functions and model mocked."""
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

    mock_get_cached_growth = AsyncMock(return_value=None)
    mock_get_historical_growth = AsyncMock(return_value=_make_growth_history(120))
    mock_save_growth = AsyncMock(return_value=None)
    mock_build_payload = MagicMock(return_value=_make_growth_payload())

    monkeypatch.setattr(ops_module, "get_cached_subscriber_growth_forecast", mock_get_cached_growth)
    monkeypatch.setattr(ops_module, "get_historical_activations_churn", mock_get_historical_growth)
    monkeypatch.setattr(ops_module, "save_subscriber_growth_forecast", mock_save_growth)
    monkeypatch.setattr(ops_module, "build_forecast_payload", mock_build_payload)

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
        yield GrowthTestContext(
            ac, mock_get_cached_growth, mock_get_historical_growth, mock_save_growth, mock_build_payload
        )

    application.dependency_overrides.clear()


# ── Subscriber Growth Forecast tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_growth_cache_hit_returns_200(growth_client: GrowthTestContext) -> None:
    """Cached projection is returned without retraining."""
    cached_payload = {**_make_growth_payload(), "cache_expires_at": "2026-06-27T10:00:00+00:00", "from_cache": True}
    growth_client.mock_cached.return_value = cached_payload

    response = await growth_client.get("/api/v1/ops/forecasts/subscriber-growth")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["from_cache"] is True
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["predicted_activations"] == 150
    growth_client.mock_build.assert_not_called()
    growth_client.mock_historical.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_growth_cache_miss_trains_and_returns_200(growth_client: GrowthTestContext) -> None:
    """Cache miss with sufficient history trains, saves, and returns the forecast."""
    growth_client.mock_cached.return_value = None
    growth_client.mock_historical.return_value = _make_growth_history(120)

    response = await growth_client.get("/api/v1/ops/forecasts/subscriber-growth")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["from_cache"] is False
    assert data["model_version"] == "gradient_boosting_v1"
    assert len(data["forecasts"]) == 1
    assert "cache_expires_at" in data
    growth_client.mock_build.assert_called_once()
    growth_client.mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscriber_growth_insufficient_history_returns_400(growth_client: GrowthTestContext) -> None:
    """Fewer than 90 active days returns 400 INSUFFICIENT_FORECAST_DATA."""
    growth_client.mock_cached.return_value = None
    growth_client.mock_historical.return_value = _make_growth_history(30)

    response = await growth_client.get("/api/v1/ops/forecasts/subscriber-growth")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_FORECAST_DATA"
    growth_client.mock_build.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_growth_force_refresh_bypasses_cache(growth_client: GrowthTestContext) -> None:
    """force_refresh=true skips the cache check and retrains."""
    growth_client.mock_cached.return_value = {
        **_make_growth_payload(),
        "from_cache": True,
        "cache_expires_at": "2026-06-27T10:00:00+00:00",
    }
    growth_client.mock_historical.return_value = _make_growth_history(120)

    response = await growth_client.get("/api/v1/ops/forecasts/subscriber-growth?force_refresh=true")

    assert response.status_code == 200
    growth_client.mock_cached.assert_not_called()
    growth_client.mock_build.assert_called_once()


@pytest.mark.asyncio
async def test_subscriber_growth_with_subscriber_role_returns_403(subscriber_client: AsyncClient) -> None:
    """Subscriber role is forbidden from the subscriber-growth endpoint."""
    resp = await _auth_get(subscriber_client, "/api/v1/ops/forecasts/subscriber-growth")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_subscriber_growth_with_no_auth_returns_401(unauthenticated_client: AsyncClient) -> None:
    """Unauthenticated request returns 401."""
    resp = await unauthenticated_client.get("/api/v1/ops/forecasts/subscriber-growth")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
