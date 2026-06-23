"""Unit tests for POST /api/v1/simulator/activate + the Notification Portal broadcaster (Story 2.9).

Covers:
  - dev token -> 200, order UPDATEd to ACTIVATED, billing_wallet_balances UPSERT with
    balance_paise = plan price, Valkey balance:{msisdn} seeded, notification.events
    event published (envelope shape, key=msisdn, dual trace propagation).
  - non-dev -> 403; missing token -> 401; no match -> 404; already ACTIVATED -> 400.
  - to_notification_broadcast masks MSISDN to [-4:] (PII hygiene) and the masked
    message reaches connected WS clients via notification_connection_manager.

The DB is faked (mimics DatabaseProtocol.transaction()); producer + cache are faked;
jwt_validator is the in-memory FakeJWTValidator. No Kafka/Postgres/Valkey needed.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_SUB_ID = "11111111-1111-4111-8111-111111111111"
_MSISDN = "+919876543210"
_ORDER_ID = "22222222-2222-4222-8222-222222222222"
_PLAN_ID = "33333333-3333-4333-8333-333333333333"
_PRICE_PAISE = 4999

# Lookup SELECT column order (see _LOOKUP_BY_* in routers/simulator.py):
# (subscriber_id, msisdn, order_id, plan_id, fulfilment_status, price_paise).
_LOOKUP_ROW: tuple = (_SUB_ID, _MSISDN, _ORDER_ID, _PLAN_ID, "KYC_VERIFIED", _PRICE_PAISE)
# FOR UPDATE SELECT returns a single column (fulfilment_status).
_LOCK_ROW: tuple = ("KYC_VERIFIED",)

_ACTIVATE_BODY: dict[str, str] = {"lookup_type": "registration_id", "lookup_value": "REG-20260623-deadbeef"}


class _FakeCursor:
    """Mimics the psycopg3 cursor subset used by the handler."""

    def __init__(self, row: tuple | None = None) -> None:
        self._row = row
        self.rowcount = 1

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Routes execute() to a scripted SELECT result; records UPDATEs/INSERTs."""

    def __init__(self, db: FakeActivateDb) -> None:
        self._db = db

    async def execute(self, sql: str, params: tuple | None = None) -> _FakeCursor:
        lowered = sql.lstrip().lower()
        self._db.calls.append((lowered, params))
        if lowered.startswith("select"):
            return _FakeCursor(row=self._db.next_select_row())
        if lowered.startswith("update"):
            self._db.updates.append((lowered, params))
            return _FakeCursor()
        if lowered.startswith("insert"):
            self._db.inserts.append((lowered, params))
            return _FakeCursor()
        return _FakeCursor()


class FakeActivateDb:
    """In-memory stand-in for the psycopg3 adapter used by the activate endpoint."""

    def __init__(self, select_rows: list[tuple | None]) -> None:
        # SELECTs consume rows from this list in order (lookup first, then FOR UPDATE).
        self._select_rows = list(select_rows)
        self.calls: list[tuple[str, tuple | None]] = []
        self.updates: list[tuple[str, tuple | None]] = []
        self.inserts: list[tuple[str, tuple | None]] = []

    def next_select_row(self) -> tuple | None:
        return self._select_rows.pop(0) if self._select_rows else None

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        yield _FakeConn(self)

    async def ping(self) -> bool:
        return True


class FakeCache:
    """Records Valkey balance seeds (CacheProtocol subset)."""

    def __init__(self) -> None:
        self.balance_seeds: list[tuple[str, int]] = []

    async def set_balance(self, msisdn: str, paise: int) -> None:
        self.balance_seeds.append((msisdn, paise))

    async def ping(self) -> bool:
        return True


class FakeProducer:
    """Minimal aiokafka producer stub that records send() calls."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, topic: str, *, value: bytes, key: bytes, headers: list) -> None:
        self.sent.append({"topic": topic, "value": json.loads(value), "key": key.decode(), "headers": headers})

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def _make_app(
    *,
    role: str = "dev",
    select_rows: list[tuple | None] | None = None,
    producer: FakeProducer | None = None,
    cache: FakeCache | None = None,
    db: FakeActivateDb | None = None,
) -> tuple[Any, FakeActivateDb, FakeCache, FakeProducer]:
    """Build an app wired to fakes; return (app, db, cache, producer)."""
    from main import create_app

    jwt = FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": [role]})
    _db = db or FakeActivateDb(select_rows or [_LOOKUP_ROW, _LOCK_ROW])
    _cache = cache or FakeCache()
    _producer = producer or FakeProducer()
    app = create_app(
        jwt_validator=jwt,
        db_adapter=_db,
        cache_adapter=_cache,
        kafka_producer=_producer,
        trace_consumer=MagicMock(),
        notification_consumer=MagicMock(),
    )
    return app, _db, _cache, _producer


async def _post(path: str, app: Any, body: dict | None = None, *, auth: bool = True) -> Any:
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer fake-token"} if auth else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body or {}, headers=headers)


# ── activate endpoint: happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_returns_200_with_activation_result():
    app, _db, _cache, _producer = _make_app()
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["order_id"] == _ORDER_ID
    assert data["status"] == "ACTIVATED"
    assert data["msisdn"] == _MSISDN
    assert data["balance_paise"] == _PRICE_PAISE


@pytest.mark.asyncio
async def test_activate_updates_order_to_activated():
    app, db, _c, _p = _make_app()
    await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    update = next((sql for sql, _ in db.updates if "ops_order_fulfilment" in sql), None)
    assert update is not None, "expected an UPDATE on ops_order_fulfilment"
    assert "'activated'" in update.replace(" ", " ").lower()


@pytest.mark.asyncio
async def test_activate_upserts_wallet_with_plan_price():
    app, db, _c, _p = _make_app()
    await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    wallet = next((p for sql, p in db.inserts if "billing_wallet_balances" in sql), None)
    assert wallet is not None, "expected an INSERT/UPSERT on billing_wallet_balances"
    # params: (subscriber_id::uuid, msisdn, price_paise)
    assert wallet[0] == _SUB_ID
    assert wallet[1] == _MSISDN
    assert wallet[2] == _PRICE_PAISE


@pytest.mark.asyncio
async def test_activate_seeds_valkey_balance():
    app, _db, cache, _p = _make_app()
    await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert cache.balance_seeds == [(_MSISDN, _PRICE_PAISE)]


@pytest.mark.asyncio
async def test_activate_publishes_notification_event():
    app, _db, _c, producer = _make_app()
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert r.status_code == 200, r.text
    assert len(producer.sent) == 1
    msg = producer.sent[0]
    assert msg["topic"] == "notification.events"
    assert msg["key"] == _MSISDN  # per-subscriber ordering key
    value = msg["value"]
    assert value["event_type"] == "notification.events"
    assert value["payload"]["msisdn"] == _MSISDN
    assert value["payload"]["notification_type"] == "SIM_ACTIVATION"
    assert value["payload"]["message_preview"]
    # trace_id appears in both the body and the traceparent header (NFR-17)
    body_trace_id = value["trace_id"]
    header_dict = dict(msg["headers"])
    header_trace_id = header_dict["traceparent"].decode().split("-")[1]
    assert body_trace_id == header_trace_id
    assert r.json()["meta"]["trace_id"] == body_trace_id


@pytest.mark.asyncio
async def test_activate_by_msisdn_lookup_resolves():
    """lookup_type=msisdn path resolves the subscriber (not just registration_id)."""
    body = {"lookup_type": "msisdn", "lookup_value": _MSISDN}
    app, _db, _c, _p = _make_app()
    r = await _post("/api/v1/simulator/activate", app, body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["msisdn"] == _MSISDN


# ── activate endpoint: auth + error matrix ───────────────────────────────────


@pytest.mark.asyncio
async def test_activate_no_auth_returns_401():
    app, _db, _c, _p = _make_app()
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY, auth=False)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_activate_wrong_role_returns_403():
    app, _db, _c, _p = _make_app(role="subscriber")
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_activate_no_match_returns_404():
    app, db, _c, _p = _make_app(select_rows=[None])  # lookup finds nothing
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_activate_already_activated_returns_400():
    app, db, _c, _p = _make_app(select_rows=[_LOOKUP_ROW, ("ACTIVATED",)])
    r = await _post("/api/v1/simulator/activate", app, _ACTIVATE_BODY)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ILLEGAL_TRANSITION"


@pytest.mark.asyncio
async def test_activate_invalid_lookup_type_returns_422():
    app, _db, _c, _p = _make_app()
    r = await _post("/api/v1/simulator/activate", app, {"lookup_type": "email", "lookup_value": "x"})
    assert r.status_code == 422


# ── Notification Portal broadcaster: PII masking + fan-out ────────────────────


_SAMPLE_ENVELOPE: dict[str, Any] = {
    "event_type": "notification.events",
    "event_id": "01923d2e-0000-7000-8000-000000000000",
    "trace_id": "a" * 32,
    "timestamp": "2026-06-23T00:00:00+00:00",
    "payload": {
        "subscriber_id": _SUB_ID,
        "msisdn": _MSISDN,
        "notification_type": "SIM_ACTIVATION",
        "channel": "SMS",
        "message_preview": "Your SIM has been activated.",
        "timestamp": "2026-06-23T00:00:00+00:00",
    },
}


def test_to_notification_broadcast_masks_msisdn_to_last4():
    from routers.simulator import to_notification_broadcast

    msg = to_notification_broadcast(_SAMPLE_ENVELOPE)
    assert msg["msisdn_suffix"] == "***3210"  # mask_msisdn: *** + last 4 of 919876543210
    assert msg["notification_type"] == "SIM_ACTIVATION"
    assert msg["message_preview"] == "Your SIM has been activated."
    assert msg["trace_id"] == "a" * 32
    # PII hygiene: the full MSISDN must never be sent over the wire
    assert _MSISDN not in json.dumps(msg)
    assert "987654" not in json.dumps(msg)


def test_to_notification_broadcast_handles_missing_payload():
    """A malformed envelope degrades to None fields rather than raising."""
    from routers.simulator import to_notification_broadcast

    msg = to_notification_broadcast({"event_type": "notification.events", "trace_id": "b" * 32})
    assert msg["msisdn_suffix"] == "***"  # mask_msisdn on empty -> "***"
    assert msg["notification_type"] is None


@pytest.mark.asyncio
async def test_notification_connection_manager_broadcasts_masked_message():
    """A notification.events envelope is fanned to connected WS clients, MSISDN masked."""
    from routers.simulator import notification_connection_manager, to_notification_broadcast

    ws = AsyncMock()
    await notification_connection_manager.connect(ws)
    try:
        msg = to_notification_broadcast(_SAMPLE_ENVELOPE)
        await notification_connection_manager.broadcast(msg)
        ws.send_json.assert_awaited_once_with(msg)
        assert msg["msisdn_suffix"] == "***3210"
    finally:
        notification_connection_manager.disconnect(ws)
