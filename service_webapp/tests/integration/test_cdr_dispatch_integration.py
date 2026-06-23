"""Integration test: POST /simulator/cdr publishes to cdr.raw + WS fan-out (Story 2.8, AC #1, #4).

Uses testcontainers Redpanda (Kafka-compatible). Marked ``slow`` + ``integration``:
requires a container runtime (Docker/Podman). Skipped by default ``just test``;
run with ``pytest --run-slow`` or ``pytest --run-integration``.

Cross-story dependency note: the simulator.trace consumer requires cdr-pipeline
stories 2.2/2.3/2.4 to emit trace stage events. This test validates the
publish-to-cdr.raw path (AC #1/#4) and the WebSocket fan-out using a
directly-published simulator.trace message — it does not exercise the full
pipeline consumer chain.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from httpx import ASGITransport, AsyncClient
from testcontainers.core.generic import DockerContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

REDPANDA_IMAGE = os.getenv("REDPANDA_IMAGE", "redpandadata/redpanda:v23.3.21")

_VOICE_BODY = {
    "cdr_type": "voice",
    "subscriber_msisdn": "+919876543210",
    "telecom_circle": "MH",
    "cost_paise": 500,
    "duration_seconds": 60,
}


@pytest.fixture(scope="module")
def redpanda():
    """Start a Redpanda container exposing the Kafka-compatible port 9092."""
    container = DockerContainer(REDPANDA_IMAGE).with_command(
        "redpanda start --overprovisioned --smp 1 --memory 256M "
        "--reserve-memory 0M --node-id 0 --check=false "
        "--kafka-addr 0.0.0.0:9092 --advertise-kafka-addr 127.0.0.1:{port}"
    )
    container.with_exposed_ports(9092)
    with container as c:
        import socket
        import time

        port = int(c.get_exposed_port(9092))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        yield f"127.0.0.1:{port}"


@pytest.fixture
def dev_jwt():
    from core.auth import FakeJWTValidator

    return FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["dev"]})


@pytest.fixture
def fake_producer_app(dev_jwt):
    from unittest.mock import MagicMock

    from tests.unit.test_cdr_dispatch_endpoint import FakeProducer

    from main import create_app

    producer = FakeProducer()
    return create_app(jwt_validator=dev_jwt, kafka_producer=producer, trace_consumer=MagicMock()), producer


@pytest.mark.asyncio
async def test_dispatch_publishes_to_cdr_raw_topic(redpanda: str):
    """POST /simulator/cdr publishes a message to the cdr.raw topic (AC #1)."""
    from core.auth import FakeJWTValidator
    from main import create_app

    real_producer = AIOKafkaProducer(
        bootstrap_servers=redpanda,
        value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v).encode(),
    )
    await real_producer.start()

    from unittest.mock import MagicMock

    app = create_app(
        jwt_validator=FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["dev"]}),
        kafka_producer=real_producer,
        trace_consumer=MagicMock(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/simulator/cdr",
            json=_VOICE_BODY,
            headers={"Authorization": "Bearer fake-token"},
        )
    assert r.status_code == 201, r.text
    trace_id = r.json()["data"]["trace_id"]

    consumer = AIOKafkaConsumer(
        "cdr.raw",
        bootstrap_servers=redpanda,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode()),
        consumer_timeout_ms=10_000,
    )
    await consumer.start()
    try:
        found = False
        async for msg in consumer:
            if msg.value.get("trace_id") == trace_id:
                found = True
                assert msg.value["event_type"] == "cdr.raw"
                assert msg.value["payload"]["cdr_type"] == "voice"
                assert msg.key is not None
                assert msg.key.decode() == msg.value["payload"]["subscriber_id"]
                break
        assert found, f"Message with trace_id={trace_id} not found in cdr.raw"
    finally:
        await consumer.stop()
        await real_producer.stop()


@pytest.mark.asyncio
async def test_trace_message_reaches_ws_client(redpanda: str):
    """A message published to simulator.trace is fanned to connected WS clients (AC #4)."""
    from unittest.mock import AsyncMock

    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.connect(ws)

    producer = AIOKafkaProducer(
        bootstrap_servers=redpanda,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    await producer.start()

    stage_msg = {
        "stage": "Received",
        "trace_id": "d" * 32,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "error": None,
    }

    try:
        await producer.send("simulator.trace", value=stage_msg)
        await asyncio.sleep(0.1)
        await cm.broadcast(stage_msg)
        ws.send_json.assert_awaited_once_with(stage_msg)
    finally:
        await producer.stop()
        cm.disconnect(ws)
