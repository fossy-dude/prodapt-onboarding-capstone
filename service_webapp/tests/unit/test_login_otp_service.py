"""Unit tests for LoginOtpService (Epic 3 — backend-driven login OTP).

Covers:
- issue() mints a 6-digit code, stores it in Valkey with TTL, publishes envelope
- verify() accepts the correct code and deletes the key (single-use)
- verify() rejects wrong code and absent key
- No-producer path does not raise (best-effort publish)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.login_otp import LoginOtpService

# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set_str(self, key: str, value: str, ex: int) -> None:
        self._store[key] = value

    async def get_str(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _FakeProducer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, topic: str, value: bytes, key: bytes, headers: list) -> None:
        self.sent.append({"topic": topic, "value": json.loads(value), "key": key.decode()})


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_issue_mints_six_digit_code() -> None:
    svc = LoginOtpService(cache=_FakeCache(), ttl_seconds=300)
    code = await svc.issue("dev", "0" * 32)
    assert len(code) == 6
    assert code.isdigit()


async def test_issue_stores_code_in_valkey() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    code = await svc.issue("dev", "0" * 32)
    stored = await cache.get_str("login_otp:dev")
    assert stored == code


async def test_issue_publishes_login_otp_event() -> None:
    producer = _FakeProducer()
    svc = LoginOtpService(cache=_FakeCache(), ttl_seconds=300, producer=producer)
    code = await svc.issue("dev", "a" * 32)

    assert len(producer.sent) == 1
    msg = producer.sent[0]
    assert msg["topic"] == "notification.events"
    payload = msg["value"]["payload"]
    assert payload["notification_type"] == "LOGIN_OTP"
    assert payload["channel"] == "SMS"
    assert code in payload["message_preview"]


async def test_issue_without_producer_does_not_raise() -> None:
    svc = LoginOtpService(cache=_FakeCache(), ttl_seconds=300, producer=None)
    code = await svc.issue("dev", "0" * 32)
    assert len(code) == 6


async def test_verify_correct_code_returns_true() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    code = await svc.issue("dev", "0" * 32)
    result = await svc.verify("dev", code)
    assert result is True


async def test_verify_deletes_key_on_success() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    code = await svc.issue("dev", "0" * 32)
    await svc.verify("dev", code)
    assert await cache.get_str("login_otp:dev") is None


async def test_verify_single_use_second_attempt_fails() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    code = await svc.issue("dev", "0" * 32)
    await svc.verify("dev", code)
    result = await svc.verify("dev", code)
    assert result is False


async def test_verify_wrong_code_returns_false() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    await svc.issue("dev", "0" * 32)
    result = await svc.verify("dev", "000000")
    assert result is False


async def test_verify_absent_key_returns_false() -> None:
    cache = _FakeCache()
    svc = LoginOtpService(cache=cache, ttl_seconds=300)
    result = await svc.verify("dev", "123456")
    assert result is False
