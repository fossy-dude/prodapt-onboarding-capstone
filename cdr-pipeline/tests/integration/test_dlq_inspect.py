"""Integration test: publish to cdr.dlq, assert GET /dlq returns it (Story 2.5, Task 6, AC #1).

Requires a live Redpanda broker (testcontainers). Marked ``slow`` — skipped in
the standard ``uv tox -e test`` run; enable with ``-m slow`` or ``pytest -m slow``.
Rootless podman: DOCKER_HOST is set via the standard testcontainers env.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from testcontainers.kafka import KafkaContainer

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def kafka_broker():
    with KafkaContainer("redpandadata/redpanda:v24.1.1") as container:
        yield container.get_bootstrap_server()


async def _publish_to_dlq(broker: str, cdr_id: str, error_reason: str) -> None:
    from aiokafka import AIOKafkaProducer

    raw = json.dumps({"cdr_id": cdr_id, "msisdn": "919876543210"}).encode()
    payload = {
        "cdr_id": cdr_id,
        "error_reason": error_reason,
        "original_topic": "cdr.raw",
        "failed_at": "2026-01-01T00:00:00+00:00",
        "raw_payload_b64": base64.b64encode(raw).decode(),
    }
    envelope = {
        "event_type": "cdr.dlq",
        "trace_id": "a" * 32,
        "payload": payload,
    }
    producer = AIOKafkaProducer(bootstrap_servers=broker)
    await producer.start()
    try:
        await producer.send_and_wait("cdr.dlq", json.dumps(envelope).encode())
    finally:
        await producer.stop()


@pytest.mark.slow
async def test_dlq_list_returns_published_record(kafka_broker: str) -> None:
    cdr_id = "integ-test-cdr-001"
    await _publish_to_dlq(kafka_broker, cdr_id, "schema_validation_error")
    await asyncio.sleep(0.5)

    from contextlib import asynccontextmanager
    from unittest.mock import patch

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.auth import FakeJWTValidator
    from core.errors import register_exception_handlers
    from management.api import router as admin_router

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield

    app = FastAPI(lifespan=_lifespan)
    register_exception_handlers(app)
    app.include_router(admin_router)
    app.state.jwt_validator = FakeJWTValidator({"sub": "u1", "cognito:groups": ["admin"]})
    from consumer.control import WorkerController

    app.state.worker_controller = WorkerController()

    with patch("management.api.settings") as mock_settings:
        mock_settings.kafka_brokers = kafka_broker
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/dlq", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 1
    found = [item for item in data["items"] if item["cdr_id"] == cdr_id]
    assert len(found) == 1, f"Expected to find {cdr_id} in DLQ response"
    assert found[0]["error_reason"] == "schema_validation_error"
    assert "919876543210" not in found[0]["raw_payload_preview"]
