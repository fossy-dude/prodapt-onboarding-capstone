"""Unit tests for RateLimitMiddleware (Story 4.3).

Tests cover:
- MVP disabled mode: pass-through with observability headers, no Valkey INCR (AC #1)
- Enabled mode: requests 1-100 pass; request 101 → 429 with RATE_LIMIT_EXCEEDED (AC #2)
- Bypass paths: /health, /ready, /api/v1/ussd/callback — no rate-limit header, no 429 (AC #6)
- Channel routing: path → channel mapping (AC #7)
- Per-channel isolation: api counter at limit does NOT block ussd (AC #3)
- retry_after: 60 - (unix_ts % 60) (AC #2)
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_jwt(phone_number: str = "+919999000001") -> str:
    """Build an unverified JWT with a phone_number claim (no signature check needed)."""
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"phone_number": phone_number, "sub": "test-sub"}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.fakesig"


class FakeCache:
    """In-memory cache stub; incr_with_expire tracks counts per key."""

    def __init__(self):
        self._counters: dict[str, int] = {}
        self.incr_calls: list[str] = []

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        self.incr_calls.append(key)
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def ping(self) -> bool:
        return True

    async def set_str(self, key, value, ex):
        pass

    async def get_str(self, key):
        return None

    async def delete(self, key):
        pass

    async def set_balance(self, msisdn, paise):
        pass

    async def get_balance(self, msisdn):
        return None

    async def incr_balance(self, msisdn, delta_paise):
        return 0


def _build_app(rate_limiting_enabled: bool, cache: FakeCache) -> FastAPI:
    """Build a minimal FastAPI app with RateLimitMiddleware wired."""
    from core.config import Settings
    from core.rate_limit import RateLimitMiddleware

    fake_settings = MagicMock(spec=Settings)
    fake_settings.rate_limiting_enabled = rate_limiting_enabled

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, settings=fake_settings)

    @app.get("/api/v1/subscriber/balance")
    async def balance():
        return PlainTextResponse("ok")

    @app.get("/health")
    async def health():
        return PlainTextResponse("ok")

    @app.get("/ready")
    async def ready():
        return PlainTextResponse("ok")

    @app.get("/api/v1/ussd/callback")
    async def ussd_callback():
        return PlainTextResponse("ok")

    @app.get("/api/v1/ussd/menu")
    async def ussd_menu():
        return PlainTextResponse("ok")

    @app.get("/api/chat/stream")
    async def chat():
        return PlainTextResponse("ok")

    app.state.cache_adapter = cache
    return app


# ── AC #1: disabled mode (MVP default) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_mode_pass_through_with_headers():
    """rate_limiting_enabled=False: 200 returned; X-RateLimit-Limit/Channel headers set."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=False, cache=cache)
    jwt = _make_jwt()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.status_code == 200
    assert resp.headers["x-ratelimit-limit"] == "100"
    assert resp.headers["x-ratelimit-channel"] == "api"


@pytest.mark.asyncio
async def test_disabled_mode_no_valkey_incr():
    """rate_limiting_enabled=False: Valkey incr_with_expire is never called."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=False, cache=cache)
    jwt = _make_jwt()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(200):
            await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

    assert cache.incr_calls == [], "incr_with_expire must not be called when rate limiting is disabled"


# ── AC #2: enabled mode — request 1-100 pass, 101 → 429 ──────────────────────


@pytest.mark.asyncio
async def test_enabled_mode_first_100_requests_pass():
    """rate_limiting_enabled=True: requests 1-100 return 200."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)
    jwt = _make_jwt()

    fixed_time = 1_700_000_000.0

    with patch("core.rate_limit.time") as mock_time:
        mock_time.time.return_value = fixed_time
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for i in range(100):
                resp = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})
                assert resp.status_code == 200, f"Request {i + 1} should pass"


@pytest.mark.asyncio
async def test_enabled_mode_101st_request_returns_429():
    """rate_limiting_enabled=True: request 101 returns 429 with RATE_LIMIT_EXCEEDED body."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)
    jwt = _make_jwt()

    fixed_time = 1_700_000_000.0

    with patch("core.rate_limit.time") as mock_time:
        mock_time.time.return_value = fixed_time
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(100):
                await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

            resp = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_enabled_mode_retry_after_value():
    """retry_after = 60 - (unix_ts % 60); Retry-After header matches."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)
    jwt = _make_jwt()

    fixed_time = 1_700_000_010.0  # 1_700_000_010 % 60 == 30 → retry_after = 30

    with patch("core.rate_limit.time") as mock_time:
        mock_time.time.return_value = fixed_time
        # Pre-fill counter past limit
        bucket = int(fixed_time) // 60
        key = f"ratelimit:+919999000001:api:{bucket}"
        cache._counters[key] = 100

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "30"
    assert "30s" in resp.json()["error"]["message"]


# ── AC #6: bypass paths — no rate-limit, no 429 ──────────────────────────────


@pytest.mark.asyncio
async def test_health_bypass_no_headers():
    """/health bypassed: no X-RateLimit headers, no 429, no incr called."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert "x-ratelimit-limit" not in resp.headers
    assert cache.incr_calls == []


@pytest.mark.asyncio
async def test_ready_bypass_no_headers():
    """/ready bypassed."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ready")

    assert resp.status_code == 200
    assert "x-ratelimit-limit" not in resp.headers


@pytest.mark.asyncio
async def test_ussd_callback_bypass():
    """/api/v1/ussd/callback with no JWT: pass-through, no rate-limit header, no 429."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/ussd/callback")

    assert resp.status_code == 200
    assert "x-ratelimit-limit" not in resp.headers
    assert cache.incr_calls == []


# ── AC #7: channel routing ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_ussd():
    """/api/v1/ussd/menu → channel=ussd in header."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=False, cache=cache)
    jwt = _make_jwt()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/ussd/menu", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.headers["x-ratelimit-channel"] == "ussd"


@pytest.mark.asyncio
async def test_channel_chatbot():
    """/api/chat/stream → channel=chatbot in header."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=False, cache=cache)
    jwt = _make_jwt()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/chat/stream", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.headers["x-ratelimit-channel"] == "chatbot"


@pytest.mark.asyncio
async def test_channel_api():
    """/api/v1/subscriber/balance → channel=api in header."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=False, cache=cache)
    jwt = _make_jwt()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.headers["x-ratelimit-channel"] == "api"


# ── AC #3: per-channel isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_channel_isolation():
    """Api counter at 100 does NOT block ussd channel."""
    cache = FakeCache()
    app = _build_app(rate_limiting_enabled=True, cache=cache)
    jwt = _make_jwt()

    fixed_time = 1_700_000_000.0
    msisdn = "+919999000001"

    with patch("core.rate_limit.time") as mock_time:
        mock_time.time.return_value = fixed_time
        bucket = int(fixed_time) // 60
        # Saturate the api channel counter
        cache._counters[f"ratelimit:{msisdn}:api:{bucket}"] = 100

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # api channel: next request (101) should be blocked
            resp_api = await client.get("/api/v1/subscriber/balance", headers={"Authorization": f"Bearer {jwt}"})
            # ussd channel: should still pass (separate counter)
            resp_ussd = await client.get("/api/v1/ussd/menu", headers={"Authorization": f"Bearer {jwt}"})

    assert resp_api.status_code == 429
    assert resp_ussd.status_code == 200
