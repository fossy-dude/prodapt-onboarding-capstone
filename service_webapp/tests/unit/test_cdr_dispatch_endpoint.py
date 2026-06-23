"""Unit tests for POST /api/v1/simulator/cdr and /ws/simulator/trace (Story 2.8).

Covers:
  - dev token → 201 + publish to cdr.raw (correct envelope, header traceparent, body trace_id equal, key=subscriber_id)
  - missing token → 401, non-dev token → 403
  - CDR payload validates against the cdr-pipeline CdrEvent schema
  - ConnectionManager connect / disconnect / broadcast
  - trace consumer fans a message to connected WS clients (mock consumer)
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

DEV_JWT = FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["dev"]})
SUB_JWT = FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["subscriber"]})


class FakeProducer:
    """Minimal aiokafka producer stub that records ``send`` calls."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, topic: str, *, value: bytes, key: bytes, headers: list) -> None:
        self.sent.append({"topic": topic, "value": json.loads(value), "key": key.decode(), "headers": headers})

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def _make_app(role: str = "dev") -> Any:
    from main import create_app

    jwt = FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": [role]})
    producer = FakeProducer()
    return create_app(jwt_validator=jwt, kafka_producer=producer, trace_consumer=MagicMock())


def _make_app_no_producer() -> Any:
    from main import create_app

    producer = None
    return create_app(
        jwt_validator=DEV_JWT,
        kafka_producer=producer,
        trace_consumer=MagicMock(),
    )


async def _post(path: str, app: Any, body: dict | None = None) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body or {}, headers={"Authorization": "Bearer fake-token"})


async def _post_no_auth(path: str, app: Any, body: dict | None = None) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body or {})


_VOICE_BODY = {
    "cdr_type": "voice",
    "subscriber_msisdn": "+919876543210",
    "telecom_circle": "MH",
    "cost_paise": 500,
    "duration_seconds": 120,
}

_SMS_BODY = {
    "cdr_type": "sms",
    "subscriber_msisdn": "+919876543210",
    "telecom_circle": "KA",
    "cost_paise": 100,
    "message_direction": "MO",
}

_DATA_BODY = {
    "cdr_type": "data",
    "subscriber_msisdn": "+919876543210",
    "telecom_circle": "DL",
    "cost_paise": 1000,
    "volume_mb": 50.0,
}


@pytest.mark.asyncio
async def test_dispatch_cdr_voice_returns_201():
    app = _make_app()
    r = await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["data"]["cdr_type"] == "voice"
    assert "trace_id" in body["data"]
    assert "trace_id" in body["meta"]


@pytest.mark.asyncio
async def test_dispatch_cdr_publishes_to_cdr_raw():
    app = _make_app()
    await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    producer: FakeProducer = app.state.kafka_producer
    assert len(producer.sent) == 1
    msg = producer.sent[0]
    assert msg["topic"] == "cdr.raw"


@pytest.mark.asyncio
async def test_dispatch_cdr_envelope_has_dual_trace():
    """trace_id in body must equal the traceparent header's trace-id (NFR-17)."""
    app = _make_app()
    await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    producer: FakeProducer = app.state.kafka_producer
    msg = producer.sent[0]
    body_trace_id = msg["value"]["trace_id"]
    header_dict = dict(msg["headers"])
    traceparent = header_dict["traceparent"].decode()
    header_trace_id = traceparent.split("-")[1]
    assert body_trace_id == header_trace_id


@pytest.mark.asyncio
async def test_dispatch_cdr_key_is_subscriber_id():
    """Kafka message key must equal the subscriber_id (per-subscriber ordering)."""
    app = _make_app()
    await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    producer: FakeProducer = app.state.kafka_producer
    msg = producer.sent[0]
    subscriber_id = msg["value"]["payload"]["subscriber_id"]
    assert msg["key"] == subscriber_id


@pytest.mark.asyncio
async def test_dispatch_cdr_payload_validates_cdr_event_schema():
    """Payload must be valid against the CdrEvent discriminated union."""
    from pydantic import TypeAdapter

    from models.cdr import CdrEvent

    adapter: TypeAdapter[CdrEvent] = TypeAdapter(CdrEvent)
    app = _make_app()
    for body in (_VOICE_BODY, _SMS_BODY, _DATA_BODY):
        r = await _post("/api/v1/simulator/cdr", app, body)
        assert r.status_code == 201, f"Expected 201 for {body['cdr_type']}: {r.text}"
        producer: FakeProducer = app.state.kafka_producer
        payload = producer.sent[-1]["value"]["payload"]
        adapter.validate_python(payload)


@pytest.mark.asyncio
async def test_dispatch_cdr_no_auth_returns_401():
    app = _make_app()
    r = await _post_no_auth("/api/v1/simulator/cdr", app, _VOICE_BODY)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_cdr_wrong_role_returns_403():
    app = _make_app(role="subscriber")
    r = await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_cdr_no_producer_returns_503():
    app = _make_app_no_producer()
    r = await _post("/api/v1/simulator/cdr", app, _VOICE_BODY)
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_dispatch_cdr_sms_returns_201():
    app = _make_app()
    r = await _post("/api/v1/simulator/cdr", app, _SMS_BODY)
    assert r.status_code == 201, r.text
    assert r.json()["data"]["cdr_type"] == "sms"


@pytest.mark.asyncio
async def test_dispatch_cdr_data_returns_201():
    app = _make_app()
    r = await _post("/api/v1/simulator/cdr", app, _DATA_BODY)
    assert r.status_code == 201, r.text
    assert r.json()["data"]["cdr_type"] == "data"


# ── ConnectionManager unit tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connection_manager_connect_adds_client():
    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.connect(ws)
    assert cm.connection_count == 1
    ws.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_manager_disconnect_removes_client():
    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.connect(ws)
    cm.disconnect(ws)
    assert cm.connection_count == 0


@pytest.mark.asyncio
async def test_connection_manager_broadcast_sends_to_all():
    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    ws1, ws2 = AsyncMock(), AsyncMock()
    await cm.connect(ws1)
    await cm.connect(ws2)
    msg = {"stage": "Received", "trace_id": "a" * 32, "timestamp": "2026-01-01T00:00:00+00:00", "error": None}
    await cm.broadcast(msg)
    ws1.send_json.assert_awaited_once_with(msg)
    ws2.send_json.assert_awaited_once_with(msg)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_removes_broken_client():
    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    good = AsyncMock()
    bad = AsyncMock()
    bad.send_json.side_effect = Exception("disconnected")
    await cm.connect(good)
    await cm.connect(bad)
    await cm.broadcast({"stage": "Received", "trace_id": "b" * 32, "timestamp": "now", "error": None})
    assert cm.connection_count == 1


# ── trace consumer fan-out test ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_consumer_fans_message_to_ws_client():
    """A simulator.trace message must reach connected WS clients."""
    from routers.simulator import ConnectionManager

    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.connect(ws)

    stage_msg = {"stage": "Received", "trace_id": "c" * 32, "timestamp": "2026-01-01T00:00:00+00:00", "error": None}
    await cm.broadcast(stage_msg)
    ws.send_json.assert_awaited_once_with(stage_msg)
