"""Tests for recharge endpoint (Story 3.5).

Critical requirements:
- Idempotency: duplicate idempotency_key returns original result (no double-charge)
- Payment method ownership validation (403 if using another subscriber's method)
- Valkey balance credit must sync with Postgres balance
- Plan activation and subscription management
- Receipt record creation
- 3-second SLA (not a hard requirement, but should be fast)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from uuid_extensions import uuid7


def _idempotency_key() -> str:
    """FR-16: idempotency keys are client-generated UUIDv7 (not v4).

    ``RechargeRequest.validate_idempotency_key`` rejects any non-v7 UUID, so the
    tests must mint v7 keys to reach the handler instead of failing at 422.
    """
    return str(uuid7())


class RechargeTestContext:
    """Holds test fixtures for recharge tests.

    The DB command functions imported by ``routers.recharge`` are patched at the
    module boundary (the correct unit-test seam): each is an ``AsyncMock`` the
    test configures with a per-function return value. This exercises the real
    handler branching (idempotency / ownership / 404 / 403) without coupling to
    the many distinct SQL queries each command issues internally.
    """

    client: AsyncClient
    mock_cache: AsyncMock
    mock_get_completed_recharge_result: AsyncMock
    mock_create_recharge_order: AsyncMock
    mock_get_payment_method_owner: AsyncMock
    mock_complete_recharge_transaction: AsyncMock
    test_sub: str
    test_msisdn: str

    def __init__(
        self,
        client: AsyncClient,
        mock_cache: AsyncMock,
        mock_get_completed_recharge_result: AsyncMock,
        mock_create_recharge_order: AsyncMock,
        mock_get_payment_method_owner: AsyncMock,
        mock_complete_recharge_transaction: AsyncMock,
        test_sub: str,
        test_msisdn: str,
    ) -> None:
        self.client = client
        self.mock_cache = mock_cache
        self.mock_get_completed_recharge_result = mock_get_completed_recharge_result
        self.mock_create_recharge_order = mock_create_recharge_order
        self.mock_get_payment_method_owner = mock_get_payment_method_owner
        self.mock_complete_recharge_transaction = mock_complete_recharge_transaction
        self.test_sub = test_sub
        self.test_msisdn = test_msisdn
        self.auth_headers = {"Authorization": "Bearer fake-token"}

    # Make the RechargeTestContext behave like the client for convenience
    async def get(self, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers)
        return await self.client.get(path, headers=headers, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers)
        return await self.client.post(path, headers=headers, **kwargs)


@pytest.fixture
async def recharge_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RechargeTestContext]:
    """App with async HTTP client + JWT middleware mocked + DB commands and cache mocked."""
    import routers.recharge as recharge_module
    from core.auth import FakeJWTValidator
    from main import create_app

    test_sub = str(uuid.uuid4())
    test_msisdn = "911234567890"
    mock_jwt_payload = {"sub": test_sub, "cognito:groups": ["subscriber"]}

    # Patch the DB command functions at the router module boundary. monkeypatch
    # restores the originals after the test, so no manual cleanup is required.
    mock_get_completed = AsyncMock(return_value=None)
    mock_create_order = AsyncMock()
    mock_get_owner = AsyncMock()
    mock_complete = AsyncMock()
    monkeypatch.setattr(recharge_module, "get_completed_recharge_result", mock_get_completed)
    monkeypatch.setattr(recharge_module, "create_recharge_order", mock_create_order)
    monkeypatch.setattr(recharge_module, "get_payment_method_owner", mock_get_owner)
    monkeypatch.setattr(recharge_module, "complete_recharge_transaction", mock_complete)

    # The transaction context manager still needs to yield a stand-in conn, but
    # the patched commands never touch it, so a bare AsyncMock suffices.
    mock_conn = AsyncMock()
    mock_db = AsyncMock()
    mock_db.transaction = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    # Mock cache (Valkey)
    mock_cache = AsyncMock()
    mock_cache.incr_balance = AsyncMock(return_value=15000)  # Return new balance
    mock_cache.set_str = AsyncMock()

    jwt_validator = FakeJWTValidator(payload=mock_jwt_payload)

    application = create_app()
    application.dependency_overrides[lambda: jwt_validator] = lambda: jwt_validator  # Override JWT validator

    # Wire up mocked adapters directly into app.state
    application.state.db_adapter = mock_db
    application.state.cache = mock_cache
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield RechargeTestContext(
            ac,
            mock_cache,
            mock_get_completed,
            mock_create_order,
            mock_get_owner,
            mock_complete,
            test_sub,
            test_msisdn,
        )

    application.dependency_overrides.clear()


# ── Happy Path Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recharge_success_creates_order_and_credits_balance(recharge_client: RechargeTestContext) -> None:
    """Happy path: recharge creates order, credits balance, activates plan, creates receipt."""
    order_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    # No existing completed order -> proceed to create a new one
    recharge_client.mock_get_completed_recharge_result.return_value = None
    # Payment method is owned by the authenticated subscriber
    recharge_client.mock_get_payment_method_owner.return_value = recharge_client.test_sub
    # create_recharge_order returns the new order row
    recharge_client.mock_create_recharge_order.return_value = {
        "id": order_id,
        "subscriber_id": recharge_client.test_sub,
        "plan_id": plan_id,
        "amount_paise": 10000,
        "status": "pending",
        "created_at": datetime.now(UTC),
    }
    # complete_recharge_transaction returns the completed result
    recharge_client.mock_complete_recharge_transaction.return_value = {
        "transaction_id": order_id,
        "new_balance_paise": 15000,
        "plan_activation_timestamp": datetime.now(UTC),
        "msisdn": recharge_client.test_msisdn,
    }

    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            "plan_id": str(plan_id),
            "payment_method_id": str(uuid.uuid4()),
            "idempotency_key": _idempotency_key(),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["data"]["transaction_id"] == str(order_id)
    assert data["data"]["new_balance_paise"] == 15000
    assert "plan_activation_timestamp" in data["data"]
    assert "/receipts/" in data["data"]["receipt_url"]

    # Verify Valkey was credited for the full amount
    recharge_client.mock_cache.incr_balance.assert_called_once_with(recharge_client.test_msisdn, 10000)


@pytest.mark.asyncio
async def test_recharge_idempotent_retry_returns_original_result(recharge_client: RechargeTestContext) -> None:
    """Idempotency: duplicate idempotency_key returns original completed order (no double-charge)."""
    idempotency_key = _idempotency_key()
    order_id = uuid.uuid4()

    # get_completed_recharge_result returns existing completed order
    recharge_client.mock_get_completed_recharge_result.return_value = {
        "transaction_id": str(order_id),
        "subscriber_id": recharge_client.test_sub,
        "amount_paise": 10000,
        "completed_at": datetime.now(UTC),
        "status": "completed",
        "new_balance_paise": 15000,
        "plan_activation_timestamp": datetime.now(UTC),
        "msisdn": recharge_client.test_msisdn,
    }

    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            "plan_id": str(uuid.uuid4()),
            "payment_method_id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["transaction_id"] == str(order_id)
    assert data["data"]["new_balance_paise"] == 15000

    # Verify the create/complete path was bypassed entirely (idempotent retry)
    recharge_client.mock_create_recharge_order.assert_not_called()
    recharge_client.mock_complete_recharge_transaction.assert_not_called()
    recharge_client.mock_cache.incr_balance.assert_not_called()


# ── Security Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recharge_403_when_payment_method_belongs_to_another_subscriber(
    recharge_client: RechargeTestContext,
) -> None:
    """Security: payment method ownership is validated (403 if not owned by subscriber)."""
    other_subscriber_id = str(uuid.uuid4())

    # No existing order, and the payment method is owned by a different subscriber
    recharge_client.mock_get_completed_recharge_result.return_value = None
    recharge_client.mock_get_payment_method_owner.return_value = other_subscriber_id

    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            "plan_id": str(uuid.uuid4()),
            "payment_method_id": str(uuid.uuid4()),
            "idempotency_key": _idempotency_key(),
        },
    )

    assert response.status_code == 403
    assert "does not belong to this subscriber" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_recharge_404_when_payment_method_not_found(recharge_client: RechargeTestContext) -> None:
    """Security: payment method must exist (404 if not found)."""
    # No existing order, and the payment method does not exist
    recharge_client.mock_get_completed_recharge_result.return_value = None
    recharge_client.mock_get_payment_method_owner.return_value = None

    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            "plan_id": str(uuid.uuid4()),
            "payment_method_id": str(uuid.uuid4()),
            "idempotency_key": _idempotency_key(),
        },
    )

    assert response.status_code == 404
    assert "Payment method not found" in response.json()["error"]["message"]


# ── Validation Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recharge_422_when_idempotency_key_is_not_valid_uuid(recharge_client: RechargeTestContext) -> None:
    """Validation: idempotency_key must be a valid UUID."""
    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            "plan_id": str(uuid.uuid4()),
            "payment_method_id": str(uuid.uuid4()),
            "idempotency_key": "not-a-uuid",
        },
    )

    assert response.status_code == 422
    # §1.11.3 envelope: error.detail is {"errors": [ {type, loc, msg, ...}, ... ]}
    errors = response.json()["error"]["detail"]["errors"]
    idempotency_errors = [e for e in errors if "idempotency_key" in str(e.get("loc", []))]
    assert len(idempotency_errors) > 0


@pytest.mark.asyncio
async def test_recharge_422_when_missing_required_fields(recharge_client: RechargeTestContext) -> None:
    """Validation: all required fields must be present."""
    response = await recharge_client.post(
        "/api/v1/subscriber/recharge",
        json={
            # Missing plan_id and payment_method_id
            "idempotency_key": _idempotency_key(),
        },
    )

    assert response.status_code == 422


# ── Integration Tests (marked as slow) ───────────────────────────────────────


@pytest.mark.slow
@pytest.mark.asyncio
async def test_recharge_credits_valkey_and_postgres_in_sync() -> None:
    """Integration: recharge credits both Valkey and Postgres; they stay in sync."""
    # This test would use testcontainers for real Postgres and Valkey
    # For now, we skip the actual implementation as it requires significant infrastructure
    # The pattern would be:
    # 1. Spin up testcontainers Postgres + Valkey
    # 2. Run recharge transaction
    # 3. Query both Valkey and Postgres for balance
    # 4. Assert they match exactly
    pytest.skip("Integration test - requires testcontainers setup")
