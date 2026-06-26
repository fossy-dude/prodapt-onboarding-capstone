"""Unit tests for the CDR management API (Story 2.5, Task 6, AC #1-#5).

Drives the FastAPI app via ``httpx.AsyncClient`` with a mocked ``JWTValidator``
(no live Cognito) and a mocked DLQ consumer (no live Redpanda). Tests:
  - Auth matrix: no token → 401, valid token without admin → 403, admin → 200 (AC #5)
  - Worker control: pause clears event, resume sets it; responses match spec (AC #3/#4)
  - DLQ list: pagination + PII masking (AC #1)
  - DLQ single event: returns full masked payload (AC #2)
"""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from consumer.control import WorkerController
from core.auth import FakeJWTValidator
from core.errors import register_exception_handlers
from management.api import router as admin_router

# ── App factory ───────────────────────────────────────────────────────────────


def _make_app(
    *,
    jwt_validator: Any = None,
    worker_controller: WorkerController | None = None,
) -> FastAPI:
    """Build a minimal management app with injected fakes."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield

    app = FastAPI(lifespan=_lifespan)
    register_exception_handlers(app)
    app.include_router(admin_router)
    app.state.jwt_validator = jwt_validator or FakeJWTValidator({"sub": "u1", "cognito:groups": ["admin"]})
    app.state.worker_controller = worker_controller or WorkerController()
    return app


def _admin_app() -> FastAPI:
    return _make_app(jwt_validator=FakeJWTValidator({"sub": "u1", "cognito:groups": ["admin"]}))


def _subscriber_app() -> FastAPI:
    return _make_app(jwt_validator=FakeJWTValidator({"sub": "u2", "cognito:groups": ["subscriber"]}))


def _no_token_app() -> FastAPI:
    return _make_app(jwt_validator=FakeJWTValidator(fail="invalid"))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _empty_dlq_patch():
    return patch("management.api._fetch_dlq_records", new=AsyncMock(return_value=[]))


def _dlq_with_records_patch(records: list[dict]):
    return patch("management.api._fetch_dlq_records", new=AsyncMock(return_value=records))


def _make_dlq_record(
    cdr_id: str = "cdr-001",
    msisdn: str = "919876543210",
    error_reason: str = "schema_validation_error",
) -> dict:
    raw = json.dumps({"cdr_id": cdr_id, "msisdn": msisdn, "imei": "12345678901234567890"})
    b64 = base64.b64encode(raw.encode()).decode()
    return {
        "cdr_id": cdr_id,
        "error_reason": error_reason,
        "original_topic": "cdr.raw",
        "failed_at": "2026-01-01T00:00:00+00:00",
        "raw_payload_b64": b64,
    }


# ── AC #5: Auth matrix ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "endpoint,method",
    [
        ("/api/v1/admin/dlq", "GET"),
        ("/api/v1/admin/dlq/some-id", "GET"),
        ("/api/v1/admin/workers/pause", "POST"),
        ("/api/v1/admin/workers/resume", "POST"),
    ],
)
async def test_no_token_returns_401(endpoint: str, method: str) -> None:
    app = _no_token_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _empty_dlq_patch():
            resp = await client.request(method, endpoint, headers={"Authorization": "Bearer bad"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "endpoint,method",
    [
        ("/api/v1/admin/dlq", "GET"),
        ("/api/v1/admin/dlq/some-id", "GET"),
        ("/api/v1/admin/workers/pause", "POST"),
        ("/api/v1/admin/workers/resume", "POST"),
    ],
)
async def test_non_admin_token_returns_403(endpoint: str, method: str) -> None:
    app = _subscriber_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _empty_dlq_patch():
            resp = await client.request(method, endpoint, headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_missing_auth_header_returns_401() -> None:
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/dlq")
    assert resp.status_code == 401


# ── AC #3/#4: Worker control ──────────────────────────────────────────────────


async def test_pause_clears_controller_event_and_returns_paused() -> None:
    controller = WorkerController()
    assert controller.is_running
    app = _make_app(worker_controller=controller)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/admin/workers/pause", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "paused"
    assert not controller.is_running


async def test_resume_sets_controller_event_and_returns_running() -> None:
    controller = WorkerController()
    controller.pause()
    assert not controller.is_running
    app = _make_app(worker_controller=controller)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/admin/workers/resume", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "running"
    assert controller.is_running


async def test_pause_blocks_batch_loop_until_resume() -> None:
    """Clearing the event parks the loop before getmany (AC #3 mechanism)."""
    controller = WorkerController()
    getmany_calls = []

    async def _fake_getmany(**_kwargs):
        # Yield to the event loop each poll. The real aiokafka getmany awaits I/O
        # (it blocks up to timeout_ms), so it always suspends; an instant mock that
        # never yields would turn run()'s loop into a tight, non-cooperative spin
        # that monopolises the loop and grows getmany_calls without bound (OOM).
        await asyncio.sleep(0.01)
        getmany_calls.append(1)
        return {}

    consumer = MagicMock()
    consumer.getmany = _fake_getmany

    from consumer.batch_processor import BatchProcessor

    processor = BatchProcessor(
        consumer=consumer,
        producer=AsyncMock(),
        cache=AsyncMock(),
        controller=controller,
    )

    async def _run_briefly():
        loop_task = asyncio.create_task(processor.run())
        await asyncio.sleep(0.05)
        controller.pause()
        # A poll already in flight when pause() lands completes and appends once,
        # then the loop parks at ``controller.running.wait()``. Let that in-flight
        # poll drain before sampling, so ``before`` is taken with the loop parked.
        await asyncio.sleep(0.05)
        before = len(getmany_calls)
        await asyncio.sleep(0.1)
        after = len(getmany_calls)
        processor.stop()
        controller.resume()
        await loop_task
        return before, after

    before, after = await _run_briefly()
    assert after == before, "getmany should not be called while controller is paused"


# ── AC #1: DLQ list + pagination + PII masking ───────────────────────────────


async def test_dlq_list_returns_paginated_items() -> None:
    records = [_make_dlq_record(cdr_id=f"cdr-{i:03d}") for i in range(5)]
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _dlq_with_records_patch(records):
            resp = await client.get(
                "/api/v1/admin/dlq?limit=3&offset=0",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 5
    assert len(data["items"]) == 3
    assert data["limit"] == 3
    assert data["offset"] == 0


async def test_dlq_list_offset_pagination() -> None:
    records = [_make_dlq_record(cdr_id=f"cdr-{i:03d}") for i in range(5)]
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _dlq_with_records_patch(records):
            resp = await client.get(
                "/api/v1/admin/dlq?limit=3&offset=3",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) == 2
    assert data["offset"] == 3


async def test_dlq_list_pii_masked_in_preview() -> None:
    records = [_make_dlq_record(msisdn="919876543210")]
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _dlq_with_records_patch(records):
            resp = await client.get("/api/v1/admin/dlq", headers={"Authorization": "Bearer tok"})
    preview = resp.json()["data"]["items"][0]["raw_payload_preview"]
    assert "919876543210" not in preview, "MSISDN must not appear unmasked in preview"
    assert "3210" in preview, "last 4 digits of MSISDN should appear"


async def test_dlq_list_empty() -> None:
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _empty_dlq_patch():
            resp = await client.get("/api/v1/admin/dlq", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0
    assert resp.json()["data"]["items"] == []


# ── AC #2: DLQ single event ───────────────────────────────────────────────────


async def test_dlq_single_event_returns_full_payload() -> None:
    records = [_make_dlq_record(cdr_id="cdr-999", msisdn="919876543210")]
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _dlq_with_records_patch(records):
            resp = await client.get("/api/v1/admin/dlq/cdr-999", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cdr_id"] == "cdr-999"
    assert "raw_payload" in data
    assert "919876543210" not in data["raw_payload"], "MSISDN must be masked in full payload too"


async def test_dlq_single_event_not_found_returns_404() -> None:
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _empty_dlq_patch():
            resp = await client.get("/api/v1/admin/dlq/nonexistent", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# ── Response envelope structure ───────────────────────────────────────────────


async def test_success_response_has_meta_trace_id() -> None:
    app = _admin_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _empty_dlq_patch():
            resp = await client.get("/api/v1/admin/dlq", headers={"Authorization": "Bearer tok"})
    assert "meta" in resp.json()
    assert "trace_id" in resp.json()["meta"]
