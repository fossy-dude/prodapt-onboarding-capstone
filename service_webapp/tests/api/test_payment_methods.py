"""Tests for payment methods endpoints (Story 1.10).

Critical security requirements:
- Raw PAN must be tokenised client-side before reaching the server
- Server rejects any token that looks like a raw PAN (13-19 digits or Luhn-valid)
- JWT sub claim must match subscriber_id (authorisation)
- Exactly one default payment method at a time
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def authenticated_client() -> AsyncIterator[AsyncClient]:
    """App with async HTTP client + JWT middleware mocked."""
    from core.auth import require_role
    from main import create_app

    # Mock the require_role decorator to inject a test JWT payload
    test_sub = str(uuid.uuid4())
    mock_jwt_payload = {"sub": test_sub, "cognito:groups": ["subscriber"]}

    def mock_require_role(role: str):
        def decorator(endpoint):
            async def wrapped(*args, jwt_payload: dict = mock_jwt_payload, **kwargs):
                return await endpoint(*args, jwt_payload=jwt_payload, **kwargs)
            return wrapped
        return decorator

    # Patch the decorator
    import routers.account as account_module
    original_require_role = account_module.require_role
    account_module.require_role = mock_require_role

    # Mock database adapter
    mock_db = AsyncMock()
    mock_conn = AsyncMock()

    # Mock transaction context manager
    async def mock_transaction():
        yield mock_conn

    mock_db.transaction.return_value = mock_transaction

    application = create_app(db_adapter=mock_db)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore original
    account_module.require_role = original_require_role


class TestAddPaymentMethod:
    """Tests for POST /account/payment-methods."""

    @pytest.mark.asyncio
    async def test_add_credit_card_success(self, authenticated_client: AsyncClient) -> None:
        """Adding a tokenised credit card succeeds (AC #1, #3)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        # Mock successful INSERT
        method_id = uuid.uuid4()
        mock_conn.fetchone.return_value = (
            str(method_id),
            "CREDIT_CARD",
            "550e8400-e29b-41d4-a716-446655440000",  # UUID token
            "•••• 4242",
            False,
            None,  # created_at
        )

        response = await authenticated_client.post(
            "/account/payment-methods",
            json={
                "type": "CREDIT_CARD",
                "token": "550e8400-e29b-41d4-a716-446655440000",
                "display_label": "•••• 4242",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "CREDIT_CARD"
        assert data["data"]["token"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["data"]["display_label"] == "•••• 4242"
        assert data["data"]["is_default"] is False
        assert data["meta"]["trace_id"]

    @pytest.mark.asyncio
    async def test_reject_raw_pan_16_digits(self, authenticated_client: AsyncClient) -> None:
        """Server rejects token that is 16 contiguous digits (raw PAN) (AC #2)."""
        response = await authenticated_client.post(
            "/account/payment-methods",
            json={
                "type": "CREDIT_CARD",
                "token": "4242424242424242",  # Raw PAN!
                "display_label": "•••• 4242",
            },
        )

        assert response.status_code == 422
        assert "token" in str(response.json()).lower()

    @pytest.mark.asyncio
    async def test_reject_raw_pan_luhn_valid(self, authenticated_client: AsyncClient) -> None:
        """Server rejects token that passes Luhn algorithm (formatted PAN) (AC #2)."""
        response = await authenticated_client.post(
            "/account/payment-methods",
            json={
                "type": "CREDIT_CARD",
                "token": "4242-4242-4242-4242",  # Formatted PAN that passes Luhn
                "display_label": "•••• 4242",
            },
        )

        assert response.status_code == 422
        assert "token" in str(response.json()).lower()

    @pytest.mark.asyncio
    async def test_accept_upi_id_as_is(self, authenticated_client: AsyncClient) -> None:
        """UPI IDs are stored as-is without tokenisation (AC #4)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        mock_conn.fetchone.return_value = (
            str(method_id),
            "UPI",
            "user@upi",  # UPI ID stored as-is
            "user@upi",
            False,
            None,
        )

        response = await authenticated_client.post(
            "/account/payment-methods",
            json={
                "type": "UPI",
                "token": "user@upi",
                "display_label": "user@upi",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "UPI"
        assert data["data"]["token"] == "user@upi"

    @pytest.mark.asyncio
    async def test_validate_required_fields(self, authenticated_client: AsyncClient) -> None:
        """Request must include type, token, and display_label."""
        response = await authenticated_client.post(
            "/account/payment-methods",
            json={"type": "CREDIT_CARD"},  # Missing token and display_label
        )

        assert response.status_code == 422


class TestListPaymentMethods:
    """Tests for GET /account/payment-methods."""

    @pytest.mark.asyncio
    async def test_list_empty(self, authenticated_client: AsyncClient) -> None:
        """Returns empty array when subscriber has no payment methods."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value
        mock_conn.fetchall.return_value = []

        response = await authenticated_client.get("/account/payment-methods")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["meta"]["trace_id"]

    @pytest.mark.asyncio
    async def test_list_multiple_methods(self, authenticated_client: AsyncClient) -> None:
        """Returns all payment methods for the subscriber (AC #5)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id_1 = uuid.uuid4()
        method_id_2 = uuid.uuid4()
        mock_conn.fetchall.return_value = [
            (str(method_id_1), "CREDIT_CARD", "uuid-token-1", "•••• 4242", True, None),
            (str(method_id_2), "UPI", "user@upi", "user@upi", False, None),
        ]

        response = await authenticated_client.get("/account/payment-methods")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["data"][0]["type"] == "CREDIT_CARD"
        assert data["data"][1]["type"] == "UPI"
        assert data["data"][0]["is_default"] is True
        assert data["data"][1]["is_default"] is False


class TestSetDefaultPaymentMethod:
    """Tests for PATCH /account/payment-methods/{id}/default."""

    @pytest.mark.asyncio
    async def test_set_default_success(self, authenticated_client: AsyncClient) -> None:
        """Setting a payment method as default clears previous default (AC #5)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        mock_conn.fetchone.return_value = ("valid-sub-id",)  # Owner check passes

        # Mock the final SELECT after UPDATE
        mock_conn.fetchone.return_value = (
            str(method_id),
            "CREDIT_CARD",
            "uuid-token",
            "•••• 4242",
            True,
            None,
        )

        response = await authenticated_client.patch(f"/account/payment-methods/{method_id}/default")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["is_default"] is True

    @pytest.mark.asyncio
    async def test_set_default_cross_subscriber_forbidden(self, authenticated_client: AsyncClient) -> None:
        """Cross-subscriber access returns 403 (AC #6)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        other_sub = str(uuid.uuid4())
        mock_conn.fetchone.return_value = (other_sub,)  # Different subscriber

        response = await authenticated_client.patch(f"/account/payment-methods/{method_id}/default")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_set_default_not_found(self, authenticated_client: AsyncClient) -> None:
        """Non-existent payment method returns 404."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value
        mock_conn.fetchone.return_value = None

        method_id = uuid.uuid4()
        response = await authenticated_client.patch(f"/account/payment-methods/{method_id}/default")

        assert response.status_code == 404


class TestDeletePaymentMethod:
    """Tests for DELETE /account/payment-methods/{id}."""

    @pytest.mark.asyncio
    async def test_delete_success(self, authenticated_client: AsyncClient) -> None:
        """Deleting a payment method succeeds with 204 response."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        mock_conn.fetchone.return_value = ("valid-sub-id",)  # Owner check passes

        response = await authenticated_client.delete(f"/account/payment-methods/{method_id}")

        assert response.status_code == 204
        assert response.content == b""

    @pytest.mark.asyncio
    async def test_delete_cross_subscriber_forbidden(self, authenticated_client: AsyncClient) -> None:
        """Cross-subscriber delete returns 403."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        other_sub = str(uuid.uuid4())
        mock_conn.fetchone.return_value = (other_sub,)  # Different subscriber

        response = await authenticated_client.delete(f"/account/payment-methods/{method_id}")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_not_found(self, authenticated_client: AsyncClient) -> None:
        """Deleting non-existent payment method returns 404."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value
        mock_conn.fetchone.return_value = None

        method_id = uuid.uuid4()
        response = await authenticated_client.delete(f"/account/payment-methods/{method_id}")

        assert response.status_code == 404


class TestPANHygiene:
    """Critical security tests: PAN never reaches database or logs (AC #2)."""

    @pytest.mark.asyncio
    async def test_reject_various_pan_formats(self, authenticated_client: AsyncClient) -> None:
        """Server rejects multiple raw PAN formats (13-19 digits, with/without spaces)."""
        pans = [
            "4222222222222",  # 13 digits
            "4242424242424242",  # 16 digits
            "378282243310005",  # 15 digits (Amex)
            "4242 4242 4242 4242",  # With spaces
            "4242-4242-4242-4242",  # With hyphens
        ]

        for pan in pans:
            response = await authenticated_client.post(
                "/account/payment-methods",
                json={"type": "CREDIT_CARD", "token": pan, "display_label": "•••• 4242"},
            )
            assert response.status_code == 422, f"Should reject PAN: {pan}"

    @pytest.mark.asyncio
    async def test_accept_uuid_tokens(self, authenticated_client: AsyncClient) -> None:
        """Server accepts UUID tokens (valid client-side tokenisation)."""
        mock_conn = authenticated_client.app.state.db_adapter.transaction.return_value.__aenter__.return_value

        method_id = uuid.uuid4()
        mock_conn.fetchone.return_value = (
            str(method_id),
            "CREDIT_CARD",
            "550e8400-e29b-41d4-a716-446655440000",
            "•••• 4242",
            False,
            None,
        )

        response = await authenticated_client.post(
            "/account/payment-methods",
            json={
                "type": "CREDIT_CARD",
                "token": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
                "display_label": "•••• 4242",
            },
        )

        assert response.status_code == 201
