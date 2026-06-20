"""Unit tests for the registration endpoint (AC #1, #2, #5, #7, #8, #9).

The endpoint is exercised with an in-memory :class:`FakeRegistrationRepository`
and :class:`FakeCognitoProvider` injected through ``create_app(registration_service=...)``,
so the full HTTP behaviour (201 envelope, 409 duplicate, 422 validation, Cognito
ordering) is verified without any database or AWS dependency.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from adapters.cognito import FakeCognitoProvider

if TYPE_CHECKING:
    import pytest
from core.errors import DuplicateMsisdnError
from core.security import mask_msisdn
from services.registration import (
    REGISTRATION_STATUS,
    PersistedRegistration,
    RegistrationCommand,
    RegistrationService,
)

_REG_ID_RE = re.compile(r"^REG-\d{8}-[0-9a-f]{8}$")


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "full_name": "Priya Sharma",
        "email": "priya@example.com",
        "msisdn": "9876543210",
        "alternate_mobile": "9123456780",
        "date_of_birth": "1995-04-12",
        "address_line1": "12 MG Road",
        "address_line2": "",
        "city": "Bengaluru",
        "state": "Karnataka",
        "pin_code": "560001",
        "id_proof_type": "Aadhaar",
        "id_proof_number": "1234-5678-9012",
        "consent": True,
    }
    payload.update(overrides)
    return payload


class FakeRegistrationRepository:
    """In-memory repository: raises DuplicateMsisdnError on a repeated MSISDN."""

    def __init__(self) -> None:
        self._existing: set[str] = set()
        self.persisted: list[RegistrationCommand] = []

    async def persist(self, cmd: RegistrationCommand) -> PersistedRegistration:
        if cmd.msisdn in self._existing:
            raise DuplicateMsisdnError(detail={"msisdn": mask_msisdn(cmd.msisdn)})
        self._existing.add(cmd.msisdn)
        self.persisted.append(cmd)
        return PersistedRegistration(
            subscriber_id=f"sub-{len(self.persisted)}",
            registration_id=cmd.registration_id,
        )


def _make_app(repo: FakeRegistrationRepository | None = None, cognito: FakeCognitoProvider | None = None):
    from main import create_app

    repo = repo or FakeRegistrationRepository()
    cognito = cognito or FakeCognitoProvider()
    return create_app(registration_service=RegistrationService(repo, cognito)), repo, cognito


async def _post(payload: dict[str, object], repo=None, cognito=None):
    app, repo, cognito = _make_app(repo, cognito)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/subscriber/register", json=payload)
    return resp, repo, cognito


async def test_register_returns_201_with_standard_envelope() -> None:
    """AC #1, #2, #5: 201 with {data:{registration_id,status}, meta:{trace_id,timestamp}}."""
    resp, _repo, cognito = await _post(_valid_payload())

    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert set(body["data"]) == {"registration_id", "status"}
    assert _REG_ID_RE.match(body["data"]["registration_id"])
    assert body["data"]["status"] == REGISTRATION_STATUS
    assert set(body["meta"]) == {"trace_id", "timestamp"}
    assert len(body["meta"]["trace_id"]) == 32  # 32-hex OTEL trace id

    # Cognito provisioning + OTP happened AFTER persist (AC #7).
    assert body["data"]["registration_id"] in cognito.provisioned
    assert cognito.verifications == ["9123456780"]  # OTP to the alternate mobile


async def test_register_response_has_no_raw_pii() -> None:
    """AC #9: the response envelope never echoes raw MSISDN/name/address."""
    resp, _, _ = await _post(_valid_payload())
    text = resp.text
    assert "9876543210" not in text
    assert "Priya Sharma" not in text
    assert "560001" not in text


async def test_register_409_on_duplicate_msisdn() -> None:
    """AC #8: a second registration with the same MSISDN → 409 DUPLICATE_MSISDN."""
    repo = FakeRegistrationRepository()
    cognito = FakeCognitoProvider()
    first, repo, cognito = await _post(_valid_payload(), repo=repo, cognito=cognito)
    assert first.status_code == 201

    second, _, _ = await _post(_valid_payload(msisdn="9876543210"), repo=repo, cognito=cognito)
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "DUPLICATE_MSISDN"
    assert "meta" in body and "trace_id" in body["meta"]
    # The detail must mask the MSISDN, never echo it raw.
    assert "9876543210" not in second.text


async def test_register_422_on_invalid_payload() -> None:
    """AC #1 (validation): invalid MSISDN + missing consent → 422 VALIDATION_ERROR."""
    resp, _, _ = await _post(_valid_payload(msisdn="not-a-number", consent=False))
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]["detail"]


async def test_register_succeeds_when_cognito_fails_post_commit() -> None:
    """Cognito-after-commit compensation: provisioning failure does NOT fail the 201."""
    cognito = FakeCognitoProvider()
    cognito.fail = True
    resp, repo, _ = await _post(_valid_payload(), cognito=cognito)
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == REGISTRATION_STATUS
    assert len(repo.persisted) == 1  # the registration was still persisted


async def test_registration_logs_only_masked_msisdn(caplog: pytest.LogCaptureFixture) -> None:
    """AC #9: logs never carry the raw MSISDN — only the masked suffix."""
    repo = FakeRegistrationRepository()
    cognito = FakeCognitoProvider()
    service = RegistrationService(repo, cognito)
    cmd = RegistrationCommand(
        full_name="Priya Sharma",
        email="priya@example.com",
        msisdn="9876543210",
        alternate_mobile="9123456780",
        date_of_birth="1995-04-12",
        address_line1="12 MG Road",
        address_line2="",
        city="Bengaluru",
        state="Karnataka",
        pin_code="560001",
        id_proof_type="Aadhaar",
        id_proof_number="1234-5678-9012",
        consent=True,
    )
    with caplog.at_level(logging.INFO, logger="services.registration"):
        await service.register(cmd)

    log_text = caplog.text
    assert "9876543210" not in log_text  # raw MSISDN never logged
    assert "***3210" in log_text  # masked form is present
