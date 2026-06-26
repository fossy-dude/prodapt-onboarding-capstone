"""Tests for GET /api/v1/subscriber/receipts/{transaction_id} (Story 3.6).

WeasyPrint is excluded from the tox test env; render_receipt_pdf is mocked in all
unit tests. decrypt_pii is also mocked (requires ENCRYPTION_KEY env var which is
not set in the test env — encryption_key defaults to empty string). A @pytest.mark.slow
integration test (real WeasyPrint + real encryption) is deferred to CI with secrets.

PII checks via capture: the endpoint passes masked MSISDN (last-4 only) and
decrypted name to render_receipt_pdf — verified via captured kwargs.
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

FAKE_PDF_BYTES = b"%PDF-1.4 fake-pdf-content"
FAKE_ENCRYPTED_NAME = "FAKE_ENCRYPTED_VALUE"
DECRYPTED_NAME = "Test Subscriber"


class ReceiptTestContext:
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
async def receipt_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ReceiptTestContext]:
    """App wired with mocked DB + JWT; render_receipt_pdf patched to return fake bytes."""
    import routers.recharge as recharge_module
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

    monkeypatch.setattr(recharge_module, "resolve_subscriber_id", _fake_resolve_subscriber_id)

    jwt_validator = FakeJWTValidator(payload=mock_jwt_payload)
    application = create_app()
    application.state.db_adapter = mock_db
    application.state.cache = AsyncMock()
    application.state.jwt_validator = jwt_validator

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ReceiptTestContext(ac, mock_conn, test_sub)

    application.dependency_overrides.clear()


def _make_receipt_row(
    transaction_id: str,
    subscriber_id: str,
    *,
    msisdn: str = "911234567890",
    method_type: str = "CREDIT_CARD",
    last_four: str = "4242",
    receipt_number: str = "REC-001",
) -> dict:
    """Build a dict matching what get_receipt_data returns."""
    return {
        "transaction_id": transaction_id,
        "subscriber_id": uuid.UUID(subscriber_id),  # Convert to UUID like real DB would
        "amount_paise": 10000,
        "transaction_date": datetime(2026, 6, 24, 10, 30, 0, tzinfo=UTC),
        "plan_name": "Basic Plan",
        "subscriber_name_encrypted": FAKE_ENCRYPTED_NAME,
        "msisdn": msisdn,
        "method_type": method_type,
        "last_four": last_four,
        "receipt_number": receipt_number,
    }


@pytest.mark.asyncio
async def test_receipt_200_returns_pdf_bytes(receipt_client: ReceiptTestContext) -> None:
    """Happy path: valid completed order → 200 application/pdf with correct headers."""
    txn_id = str(uuid.uuid4())

    with (
        patch(
            "routers.recharge.get_receipt_data",
            return_value=_make_receipt_row(txn_id, receipt_client.test_sub),
        ),
        patch("routers.recharge.decrypt_pii", return_value=DECRYPTED_NAME),
        patch("routers.recharge.render_receipt_pdf", return_value=FAKE_PDF_BYTES),
    ):
        response = await receipt_client.get(f"/api/v1/subscriber/receipts/{txn_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert f'filename="receipt_{txn_id}.pdf"' in response.headers["content-disposition"]
    assert response.content == FAKE_PDF_BYTES


@pytest.mark.asyncio
async def test_receipt_403_owner_mismatch(receipt_client: ReceiptTestContext) -> None:
    """Other subscriber's transaction → 403 Forbidden."""
    txn_id = str(uuid.uuid4())
    other_sub = str(uuid.uuid4())

    with (
        patch(
            "routers.recharge.get_receipt_data",
            return_value=_make_receipt_row(txn_id, other_sub),
        ),
        patch("routers.recharge.decrypt_pii", return_value=DECRYPTED_NAME),
    ):
        response = await receipt_client.get(f"/api/v1/subscriber/receipts/{txn_id}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_receipt_404_not_found_or_not_completed(receipt_client: ReceiptTestContext) -> None:
    """Non-existent or non-completed order → 404 Not Found."""
    txn_id = str(uuid.uuid4())

    with patch("routers.recharge.get_receipt_data", return_value=None):
        response = await receipt_client.get(f"/api/v1/subscriber/receipts/{txn_id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_receipt_pii_msisdn_masked(receipt_client: ReceiptTestContext) -> None:
    """Endpoint passes last-4 of MSISDN to render; full number not forwarded."""
    txn_id = str(uuid.uuid4())
    full_msisdn = "911234567890"

    captured: dict = {}

    def _capture_pdf(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return FAKE_PDF_BYTES

    with (
        patch(
            "routers.recharge.get_receipt_data",
            return_value=_make_receipt_row(txn_id, receipt_client.test_sub, msisdn=full_msisdn),
        ),
        patch("routers.recharge.decrypt_pii", return_value=DECRYPTED_NAME),
        patch("routers.recharge.render_receipt_pdf", side_effect=_capture_pdf),
    ):
        response = await receipt_client.get(f"/api/v1/subscriber/receipts/{txn_id}")

    assert response.status_code == 200
    assert captured["msisdn_last4"] == "7890"
    assert captured["subscriber_name"] == DECRYPTED_NAME
    assert full_msisdn not in captured["msisdn_last4"]


@pytest.mark.asyncio
async def test_receipt_401_unauthenticated(receipt_client: ReceiptTestContext) -> None:
    """No auth header → 401."""
    txn_id = str(uuid.uuid4())
    response = await receipt_client.client.get(f"/api/v1/subscriber/receipts/{txn_id}")
    assert response.status_code == 401
