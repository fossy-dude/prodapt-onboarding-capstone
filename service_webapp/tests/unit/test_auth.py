"""Unit tests for Story 1.8 / Epic 3: JWT auth guard, step-up OTP, and login endpoints.

All Cognito and Valkey dependencies are mocked via fake implementations; no live
services are required.

Coverage:
- JWT validation: valid token passes, expired → 401, invalid → 401
- Role guard: matching group passes, mismatch → 403, missing header → 401
- Step-up OTP: generate → validate → key deleted; wrong/expired code → False
- Login endpoints: initiate publishes OTP, verify returns tokens, bad OTP → 401
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from adapters.cognito import FakeCognitoProvider
from core.auth import FakeJWTValidator
from core.errors import UnauthenticatedError
from core.login_otp import FakeLoginOtpService
from core.step_up import FakeStepUpOtpService, StepUpOtpService

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_app(
    cognito: FakeCognitoProvider | None = None,
    jwt_validator: FakeJWTValidator | None = None,
    step_up: FakeStepUpOtpService | None = None,
    login_otp: FakeLoginOtpService | None = None,
):
    from main import create_app

    return create_app(
        cognito_provider=cognito or FakeCognitoProvider(),
        jwt_validator=jwt_validator or FakeJWTValidator(),
        step_up_service=step_up or FakeStepUpOtpService(),
        login_otp_service=login_otp or FakeLoginOtpService(),
    )


async def _client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: JWTValidator / FakeJWTValidator decode behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_fake_jwt_validator_returns_payload() -> None:
    payload = {"sub": "abc-123", "cognito:groups": ["subscriber"]}
    validator = FakeJWTValidator(payload=payload)
    assert validator.decode("any.token.here") == payload


def test_fake_jwt_validator_expired_raises() -> None:
    validator = FakeJWTValidator(fail="expired")
    with pytest.raises(UnauthenticatedError, match="expired"):
        validator.decode("any.token")


def test_fake_jwt_validator_invalid_raises() -> None:
    validator = FakeJWTValidator(fail="invalid")
    with pytest.raises(UnauthenticatedError, match="invalid"):
        validator.decode("any.token")


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: require_role — via a guarded test endpoint wired into the app
# ─────────────────────────────────────────────────────────────────────────────


async def _role_guarded_client(
    groups: list[str] | None = None,
    fail: str | None = None,
    required_roles: tuple[str, ...] = ("subscriber",),
):
    """Build a minimal app with one role-guarded test route and return an async client."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from core.auth import require_role
    from core.errors import register_exception_handlers

    validator = FakeJWTValidator(
        payload={"sub": "user-1", "cognito:groups": groups or []},
        fail=fail,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.state.jwt_validator = validator

    @app.get("/protected")
    async def protected(payload: dict = require_role(*required_roles)):
        return JSONResponse({"sub": payload.get("sub")})

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_role_guard_passes_with_valid_token_and_matching_group() -> None:
    async with await _role_guarded_client(groups=["subscriber"]) as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer valid.token.here"})
    assert resp.status_code == 200
    assert resp.json()["sub"] == "user-1"


async def test_role_guard_401_on_missing_authorization_header() -> None:
    async with await _role_guarded_client() as ac:
        resp = await ac.get("/protected")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"


async def test_role_guard_401_on_expired_token() -> None:
    async with await _role_guarded_client(fail="expired") as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer expired.token"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_role_guard_401_on_invalid_token() -> None:
    async with await _role_guarded_client(fail="invalid") as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer bad.token"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_role_guard_403_on_wrong_group() -> None:
    async with await _role_guarded_client(groups=["ops"], required_roles=("subscriber",)) as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer valid.token"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_role_guard_passes_any_listed_role() -> None:
    """Caller with 'ops' group passes a guard that accepts ops or admin."""
    async with await _role_guarded_client(groups=["ops"], required_roles=("subscriber", "ops")) as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer valid.token"})
    assert resp.status_code == 200


async def test_role_guard_no_pii_in_error_detail() -> None:
    """Error responses must never contain token internals (§1.11.3)."""
    async with await _role_guarded_client(fail="invalid") as ac:
        resp = await ac.get("/protected", headers={"Authorization": "Bearer secret.jwt.data"})
    assert "secret.jwt.data" not in resp.text
    assert "token_internals" not in resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Task 3: Step-up OTP service
# ─────────────────────────────────────────────────────────────────────────────


class _FakeCacheProtocol:
    """Minimal in-memory cache for StepUpOtpService unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def set_str(self, key: str, value: str, ex: int) -> None:
        self._store[key] = value

    async def get_str(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


async def test_step_up_generate_stores_and_verify_succeeds() -> None:
    cache = _FakeCacheProtocol()
    svc = StepUpOtpService(cache, ttl_seconds=300)

    code = await svc.generate("9876543210")
    assert len(code) == 6
    assert code.isdigit()

    result = await svc.verify("9876543210", code)
    assert result is True


async def test_step_up_verify_deletes_key_on_success() -> None:
    cache = _FakeCacheProtocol()
    svc = StepUpOtpService(cache, ttl_seconds=300)
    code = await svc.generate("9876543210")

    await svc.verify("9876543210", code)
    # Key must be gone after successful verification (single-use).
    assert await cache.get_str("otp:9876543210") is None


async def test_step_up_wrong_code_returns_false() -> None:
    cache = _FakeCacheProtocol()
    svc = StepUpOtpService(cache, ttl_seconds=300)
    await svc.generate("9876543210")

    result = await svc.verify("9876543210", "000000")
    assert result is False


async def test_step_up_absent_key_returns_false() -> None:
    cache = _FakeCacheProtocol()
    svc = StepUpOtpService(cache, ttl_seconds=300)
    # No generate — key was never set (or expired).
    result = await svc.verify("9876543210", "123456")
    assert result is False


async def test_step_up_key_gone_after_expiry_simulation() -> None:
    """Simulate TTL expiry by manually removing the key before verify."""
    cache = _FakeCacheProtocol()
    svc = StepUpOtpService(cache, ttl_seconds=300)
    code = await svc.generate("9876543210")
    await cache.delete("otp:9876543210")  # simulate expiry

    result = await svc.verify("9876543210", code)
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: Login endpoints (via FakeCognitoProvider + FakeLoginOtpService)
# ─────────────────────────────────────────────────────────────────────────────


async def test_login_initiate_publishes_otp() -> None:
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login/initiate", json={"identifier": "REG-20260622-ab12cd34"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == {}
    assert "REG-20260622-ab12cd34" in cognito.login_initiations
    assert len(login_otp.published_login_otps) == 1
    assert login_otp.published_login_otps[0]["identifier"] == "REG-20260622-ab12cd34"


async def test_login_verify_correct_otp_returns_tokens() -> None:
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/login/initiate", json={"identifier": "REG-20260622-ab12cd34"})
        otp_code = login_otp.issued[0]
        resp = await ac.post(
            "/api/v1/auth/login/verify",
            json={"identifier": "REG-20260622-ab12cd34", "otp": otp_code},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"] == FakeCognitoProvider.TOKENS["access_token"]
    assert data["token_type"] == "Bearer"


async def test_login_verify_wrong_otp_returns_401() -> None:
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/login/initiate", json={"identifier": "REG-20260622-ab12cd34"})
        resp = await ac.post(
            "/api/v1/auth/login/verify",
            json={"identifier": "REG-20260622-ab12cd34", "otp": "999999"},
        )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "OTP_INVALID"


async def test_login_verify_msisdn_present_in_token_response() -> None:
    # DN1: AC #2 — post-activation MSISDN login must return a token payload containing
    # phone_number. FakeCognitoProvider includes the claim; production requires a
    # PreTokenGeneration Lambda (documented in scripts/provision_cognito.py).
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/login/initiate", json={"identifier": "9876543210"})
        otp_code = login_otp.issued[0]
        resp = await ac.post(
            "/api/v1/auth/login/verify",
            json={"identifier": "9876543210", "otp": otp_code},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    # The token response envelope must include phone_number (AC #2).
    assert "phone_number" in data
    assert data["phone_number"] == FakeCognitoProvider.TOKENS["phone_number"]


async def test_login_verify_response_has_standard_envelope() -> None:
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/v1/auth/login/initiate", json={"identifier": "REG-20260622-ab12cd34"})
        otp_code = login_otp.issued[0]
        resp = await ac.post(
            "/api/v1/auth/login/verify",
            json={"identifier": "REG-20260622-ab12cd34", "otp": otp_code},
        )

    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert "trace_id" in body["meta"]
    assert "timestamp" in body["meta"]


async def test_login_initiate_no_pii_in_response() -> None:
    """Response must never echo identifier (MSISDN or Registration ID) in body."""
    cognito = FakeCognitoProvider()
    login_otp = FakeLoginOtpService()
    app = _make_app(cognito=cognito, login_otp=login_otp)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login/initiate", json={"identifier": "9876543210"})

    # Raw identifier must not appear in the response body.
    assert "9876543210" not in resp.text
