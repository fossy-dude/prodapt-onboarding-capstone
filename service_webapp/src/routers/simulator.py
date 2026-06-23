"""Simulator developer-tool router (FR-68 to FR-70; architecture §1.12.1).

Story 1.7 adds a state-advance endpoint so developers can drive
``ops_order_fulfilment`` through the activation state machine without
wiring real KYC or operator backends.

Story 2.8 adds:
  - POST /api/v1/simulator/cdr — dispatch a synthetic CDR to ``cdr.raw`` (AC #1)
  - WS  /ws/simulator/trace  — stream pipeline stage events to connected clients (AC #2, #3, #4)

Story 2.9 adds:
  - POST /api/v1/simulator/activate — drive a NEW_ACTIVATION order straight to
    ``ACTIVATED`` (order state + completed_at), seed the wallet balance
    (``billing_wallet_balances.balance_paise`` = plan price) + the Valkey
    ``balance:{msisdn}`` counter, and publish a ``notification.events`` event.
  - WS  /ws/notifications — broadcast every ``notification.events`` message
    (MSISDN masked to ``[-4:]`` server-side) to the Notification Portal.

Variance vs epic: role is ``dev`` (not ``admin``); frontend path is
``portals/simulator/`` (not ``pages/simulator/``). See Story 2.8/2.9 Dev Notes.

MSISDN variance (Story 2.9): the epic text says activation "generates" the
subscriber's MSISDN, but Story 1.6 already stores the MSISDN being activated on
``identity_subscribers.msisdn`` ("mobile to activate" — the SIM's allocated
number, NOT the alternate backup). Activation therefore REUSES the stored
MSISDN rather than generating/overwriting it. See Story 2.9 Dev Notes +
Completion Notes.

State machine (forward-only):
    CREATED → KYC_PENDING → KYC_VERIFIED → ACTIVATED
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, TypeAdapter

from core.auth import require_role
from core.errors import DomainError, NotFoundError, UnauthenticatedError
from core.responses import success_envelope
from core.security import mask_msisdn
from models.cdr import CdrEvent, CdrType
from models.envelope import EventEnvelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])

_STATE_MACHINE: dict[str, str] = {
    "CREATED": "KYC_PENDING",
    "KYC_PENDING": "KYC_VERIFIED",
    "KYC_VERIFIED": "ACTIVATED",
}

_CDR_EVENT_ADAPTER: TypeAdapter[CdrEvent] = TypeAdapter(CdrEvent)


class ConnectionManager:
    """Track active WebSocket clients and broadcast messages to all of them.

    Lifecycle: ``connect`` accepts + registers a WS; ``disconnect`` removes it;
    ``broadcast`` sends a JSON-serialisable payload to every active client.
    """

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept the WebSocket and register it as an active client."""
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket from the active set."""
        self._active.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send ``message`` to every active client; silently drop broken connections."""
        disconnected: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._active.discard(ws)

    @property
    def connection_count(self) -> int:
        """Return the number of currently active WebSocket connections."""
        return len(self._active)


connection_manager = ConnectionManager()

# Dedicated broadcaster for the Notification Portal (Story 2.9). The class is
# shared with the trace WS; a separate INSTANCE keeps notification clients from
# receiving trace stage events (and vice-versa).
notification_connection_manager = ConnectionManager()

# WS routes for the simulator sit on a NON-prefixed router so the mounted paths
# are the exact ones the frontend/ACs expect (``/ws/notifications``) rather than
# ``/api/v1/simulator/ws/notifications``.
ws_router = APIRouter(tags=["simulator"])


class CdrDispatchRequest(BaseModel):
    """Request body for POST /api/v1/simulator/cdr.

    Only the CDR type is required at this layer; type-specific fields are
    validated by the ``CdrEvent`` discriminated union via the payload dict.
    """

    cdr_type: CdrType
    subscriber_msisdn: str = Field(..., description="Subscriber MSISDN (used as subscriber_id lookup key)")
    telecom_circle: str = Field(default="MH", max_length=50)
    cell_tower_id: str | None = Field(default=None, max_length=100)
    roaming: bool = False
    cost_paise: int = Field(default=0, ge=0)
    timestamp: str | None = Field(default=None, description="ISO-8601 UTC timestamp; defaults to now")
    duration_seconds: int | None = Field(default=None, ge=0, description="Voice only")
    volume_mb: float | None = Field(default=None, ge=0, description="Data only")
    message_direction: str | None = Field(default=None, description="SMS only: MO or MT")


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _validate_order_id(order_id: str) -> None:
    """Reject non-UUID ``order_id`` path params as 404 before they reach SQL.

    A malformed value would otherwise hit the ``%s::uuid`` cast and raise a
    psycopg ``DataError`` → unhandled 500.
    """
    try:
        uuid.UUID(order_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError("Order not found.") from exc


def _build_cdr_payload(body: CdrDispatchRequest, subscriber_id: uuid.UUID) -> dict[str, Any]:
    """Construct the CDR payload dict compatible with the cdr-pipeline CdrEvent schema."""
    now = datetime.now(UTC)
    start_time = now.isoformat()

    base: dict[str, Any] = {
        "cdr_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "subscriber_id": str(subscriber_id),
        "cdr_type": body.cdr_type,
        "telecom_circle": body.telecom_circle,
        "cell_tower_id": body.cell_tower_id,
        "roaming": body.roaming,
        "cost_paise": body.cost_paise,
        "start_time": start_time,
    }

    if body.cdr_type == "voice":
        base["from_number"] = (
            body.subscriber_msisdn if body.subscriber_msisdn.startswith("+") else f"+91{body.subscriber_msisdn[-10:]}"
        )
        base["to_number"] = "+919999999999"
        base["call_direction"] = "MO"
        base["duration_seconds"] = body.duration_seconds if body.duration_seconds is not None else 60
        base["call_status"] = "answered"
    elif body.cdr_type == "data":
        vol = body.volume_mb if body.volume_mb is not None else 10.0
        base["network_type"] = "4G"
        base["volume_mb"] = vol
        base["downloaded_mb"] = vol
        base["uploaded_mb"] = 0.0
    elif body.cdr_type == "sms":
        base["message_direction"] = body.message_direction if body.message_direction in ("MO", "MT") else "MO"
        base["sms_status"] = "delivered"

    return base


@router.post("/cdr", status_code=201)
async def dispatch_cdr(
    body: CdrDispatchRequest,
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """Dispatch a synthetic CDR event to the ``cdr.raw`` Kafka topic (AC #1, Story 2.8).

    Reuses the OTEL ``request.state.trace_id`` for end-to-end trace continuity:
    HTTP span → Kafka header → cdr-pipeline consumer (NFR-17).

    The subscriber_id is a synthetic UUID derived deterministically from the MSISDN
    for the simulator — no DB lookup is performed so the simulator works without
    real subscriber rows.
    """
    producer = getattr(request.app.state, "kafka_producer", None)
    if producer is None:
        err = DomainError("Kafka producer is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err

    trace_id = getattr(request.state, "trace_id", "0" * 32)
    subscriber_id = uuid.uuid5(uuid.NAMESPACE_DNS, body.subscriber_msisdn)
    cdr_payload = _build_cdr_payload(body, subscriber_id)

    _CDR_EVENT_ADAPTER.validate_python(cdr_payload)

    envelope = EventEnvelope.new(
        event_type="cdr.raw",
        payload=cdr_payload,
        trace_id=trace_id,
    )
    envelope_bytes = envelope.model_dump_json().encode()

    traceparent = f"00-{trace_id}-{'0' * 16}-01"
    headers = [("traceparent", traceparent.encode())]

    await producer.send(
        "cdr.raw",
        value=envelope_bytes,
        key=str(subscriber_id).encode(),
        headers=headers,
    )

    logger.info(
        "simulator dispatch cdr cdr_type=%s subscriber=%s trace_id=%s", body.cdr_type, body.subscriber_msisdn, trace_id
    )

    return JSONResponse(
        status_code=201,
        content=success_envelope(
            {"trace_id": trace_id, "cdr_type": body.cdr_type, "subscriber_msisdn": body.subscriber_msisdn},
            trace_id=trace_id,
        ),
    )


@router.websocket("/ws/simulator/trace")
async def simulator_trace_ws(ws: WebSocket) -> None:
    """Stream pipeline stage events to connected developer clients (AC #2, #3, #4).

    Auth: JWT passed as ``?token=<bearer>`` query param.
    Message shape: ``{stage, timestamp, trace_id, error}`` (NFR-15).

    The broadcaster task (started in lifespan) fans incoming ``simulator.trace``
    Kafka messages to all active connections. This endpoint only manages the WS
    lifecycle (accept, keep-alive, disconnect).
    """
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return

    validator = getattr(ws.app.state, "jwt_validator", None)
    if validator is None:
        await ws.close(code=4001)
        return

    try:
        payload = validator.decode(token)
        groups: list[str] = payload.get("cognito:groups") or []
        if "dev" not in groups:
            await ws.close(code=4003)
            return
    except UnauthenticatedError:
        await ws.close(code=4001)
        return

    await connection_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(ws)


# ── SIM activation (Story 2.9) ────────────────────────────────────────────────


class ActivateRequest(BaseModel):
    """Request body for POST /api/v1/simulator/activate (AC #1)."""

    lookup_type: Literal["msisdn", "registration_id"]
    lookup_value: str = Field(..., min_length=1, description="MSISDN or Registration ID to look up")


# Resolve the subscriber + their NEW_ACTIVATION order + plan price. Two SQLs
# (not a branchy single query) keep the join set clean per lookup type.
_LOOKUP_BY_MSISDN = """
    SELECT s.id::text, s.msisdn, o.id::text, o.plan_id::text, o.fulfilment_status, p.price_paise
      FROM identity_subscribers s
      JOIN ops_order_fulfilment o
        ON o.subscriber_id = s.id AND o.fulfilment_type = 'NEW_ACTIVATION'
      JOIN plans_plans p ON p.id = o.plan_id
     WHERE s.msisdn = %s
     ORDER BY o.created_at DESC
     LIMIT 1
"""

_LOOKUP_BY_REGISTRATION_ID = """
    SELECT s.id::text, s.msisdn, o.id::text, o.plan_id::text, o.fulfilment_status, p.price_paise
      FROM identity_registrations reg
      JOIN identity_subscribers s ON s.id = reg.subscriber_id
      JOIN ops_order_fulfilment o
        ON o.subscriber_id = s.id AND o.fulfilment_type = 'NEW_ACTIVATION'
      JOIN plans_plans p ON p.id = o.plan_id
     WHERE reg.registration_id = %s
     ORDER BY o.created_at DESC
     LIMIT 1
"""

_NOTIFICATION_TOPIC = "notification.events"


def to_notification_broadcast(envelope_value: Any) -> dict[str, Any]:
    """Mask a ``notification.events`` envelope into the WS client message shape.

    PII hygiene (§1.11.6): the full MSISDN is NEVER sent over the wire — only the
    ``[-4:]`` suffix. The envelope ``payload`` carries the raw MSISDN; this helper
    masks it before broadcast. Returns the portal's WS contract::

        {msisdn_suffix, notification_type, message_preview, timestamp, trace_id}
    """
    value: dict[str, Any] = envelope_value if isinstance(envelope_value, dict) else {}
    payload: dict[str, Any] = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    msisdn = payload.get("msisdn") or ""
    return {
        "msisdn_suffix": mask_msisdn(msisdn),
        "notification_type": payload.get("notification_type"),
        "message_preview": payload.get("message_preview"),
        "timestamp": payload.get("timestamp") or value.get("timestamp"),
        "trace_id": value.get("trace_id"),
    }


async def _publish_activation_notification(
    request: Request,
    trace_id: str,
    subscriber_id: str,
    msisdn: str,
) -> None:
    """Publish a ``notification.events`` event for a SIM activation (AC #3).

    Best-effort: a missing producer (dev env without Redpanda) is logged, not
    raised — the activation side-effects (order state, wallet, Valkey seed) are
    the source of truth; the notification is observability for the portal.
    """
    producer = getattr(request.app.state, "kafka_producer", None)
    if producer is None:
        logger.warning(
            "kafka_producer not initialised — activation notification not published (msisdn=%s)", mask_msisdn(msisdn)
        )
        return

    payload = {
        "subscriber_id": subscriber_id,
        "msisdn": msisdn,
        "notification_type": "SIM_ACTIVATION",
        "channel": "SMS",
        "message_preview": "Your SIM has been activated.",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    envelope = EventEnvelope.new(event_type=_NOTIFICATION_TOPIC, payload=payload, trace_id=trace_id)
    traceparent = f"00-{trace_id}-{'0' * 16}-01"
    headers = [("traceparent", traceparent.encode())]
    await producer.send(
        _NOTIFICATION_TOPIC,
        value=envelope.model_dump_json().encode(),
        key=msisdn.encode(),
        headers=headers,
    )


@router.post("/activate", status_code=200)
async def activate_subscriber(
    body: ActivateRequest,
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """Activate a subscriber's SIM: order → ACTIVATED, wallet seeded, balance seeded, notification published.

    Resolves the subscriber by MSISDN or Registration ID → their ``NEW_ACTIVATION``
    order → plan price. The order is driven straight to ``ACTIVATED`` (a dev
    convenience — no need to click through the state machine), the wallet row is
    seeded with the plan's price in paise, and after commit the Valkey
    ``balance:{msisdn}`` counter is seeded so the subscriber is immediately
    billable. A ``notification.events`` event is then published for the portal.

    MSISDN is reused (Story 1.6 already stores the "mobile to activate"); it is
    NOT generated here. 404 when no subscriber/order matches; 400
    ``ILLEGAL_TRANSITION`` when the order is already ``ACTIVATED``.
    """
    db = _db(request)
    trace_id = getattr(request.state, "trace_id", "0" * 32)

    async with db.transaction() as conn:
        sql = _LOOKUP_BY_MSISDN if body.lookup_type == "msisdn" else _LOOKUP_BY_REGISTRATION_ID
        cur = await conn.execute(sql, (body.lookup_value,))
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("No subscriber with an activation order matched the lookup.")
        subscriber_id, msisdn, order_id, _plan_id, _status, price_paise = row

        # Lock the order before transitioning so two concurrent activations
        # cannot both flip it to ACTIVATED.
        cur = await conn.execute(
            "SELECT fulfilment_status FROM ops_order_fulfilment WHERE id = %s::uuid FOR UPDATE",
            (order_id,),
        )
        locked = await cur.fetchone()
        if locked is None:
            raise NotFoundError("Order not found.")
        if (locked[0] or "") == "ACTIVATED":
            err = DomainError("Order is already in terminal state 'ACTIVATED'.")
            err.code = "ILLEGAL_TRANSITION"
            err.http_status = 400
            raise err

        await conn.execute(
            """
            UPDATE ops_order_fulfilment
               SET fulfilment_status = 'ACTIVATED',
                   completed_at = NOW(),
                   modified_at = NOW()
             WHERE id = %s::uuid
            """,
            (order_id,),
        )
        await conn.execute(
            """
            INSERT INTO billing_wallet_balances (subscriber_id, msisdn, balance_paise, last_recharge_at)
            VALUES (%s::uuid, %s, %s, NOW())
            ON CONFLICT (subscriber_id) DO UPDATE
               SET balance_paise = EXCLUDED.balance_paise,
                   msisdn = EXCLUDED.msisdn,
                   last_recharge_at = NOW(),
                   modified_at = NOW()
            """,
            (subscriber_id, msisdn, price_paise),
        )
    # ── transaction committed; side-effects that may be best-effort follow ──

    cache = getattr(request.app.state, "cache_adapter", None)
    if cache is not None:
        try:
            await cache.set_balance(msisdn, price_paise)
        except Exception as exc:
            # Best-effort: Postgres wallet is the source of truth; cdr-pipeline can
            # warm Valkey from it. Log masked MSISDN only.
            logger.warning("Valkey balance seed failed (msisdn=%s): %s", mask_msisdn(msisdn), exc)
    else:
        logger.warning("cache_adapter not initialised — balance seed skipped (msisdn=%s)", mask_msisdn(msisdn))

    await _publish_activation_notification(request, trace_id, subscriber_id, msisdn)

    logger.info(
        "simulator activate order_id=%s subscriber=%s msisdn=%s balance_paise=%s",
        order_id,
        subscriber_id,
        mask_msisdn(msisdn),
        price_paise,
    )

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"order_id": order_id, "status": "ACTIVATED", "msisdn": msisdn, "balance_paise": price_paise},
            trace_id=trace_id,
        ),
    )


@ws_router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket) -> None:
    """Broadcast ``notification.events`` messages to the Notification Portal (AC #3, #4).

    Auth: JWT passed as ``?token=<bearer>`` query param (mirrors the 2.8 trace WS).
    The broadcaster task (lifespan) fans incoming ``notification.events`` Kafka
    messages — with MSISDN masked to ``[-4:]`` server-side (PII hygiene) — to all
    active connections. This endpoint only manages the WS lifecycle.
    """
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return

    validator = getattr(ws.app.state, "jwt_validator", None)
    if validator is None:
        await ws.close(code=4001)
        return

    try:
        payload = validator.decode(token)
        groups: list[str] = payload.get("cognito:groups") or []
        if "dev" not in groups:
            await ws.close(code=4003)
            return
    except UnauthenticatedError:
        await ws.close(code=4001)
        return

    await notification_connection_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        notification_connection_manager.disconnect(ws)


@router.get("/orders", status_code=200)
async def list_orders(
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """List recent ``ops_order_fulfilment`` rows for the simulator dev tool (AC #6).

    Returns up to 100 most-recent orders with their id + current state so the dev
    tool can populate its table without a separate seeding step. No MSISDN is
    returned (PII hygiene — the dev tool does not need raw PII to advance state).
    """
    db = _db(request)
    async with db.transaction() as conn:
        cur = await conn.execute(
            """
            SELECT id::text, fulfilment_status, created_at
            FROM ops_order_fulfilment
            ORDER BY created_at DESC
            LIMIT 100
            """,
        )
        rows = await cur.fetchall()
    orders = [
        {
            "order_id": row[0],
            "current_status": row[1],
            "created_at": row[2].isoformat() if row[2] is not None else None,
        }
        for row in rows
    ]
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"orders": orders},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


@router.post("/orders/{order_id}/advance", status_code=200)
async def advance_order_state(
    order_id: str,
    request: Request,
    _jwt: dict = require_role("dev"),
) -> JSONResponse:
    """Advance ``order_id`` one step through the activation state machine (AC #6).

    Only forward transitions are permitted. Advancing from ``ACTIVATED`` (terminal)
    returns HTTP 400 (``ILLEGAL_TRANSITION``); a row in an unknown state returns
    HTTP 409 (``UNKNOWN_STATE``). Unknown orders return HTTP 404.

    The row is locked ``FOR UPDATE`` and the UPDATE carries an optimistic
    ``fulfilment_status = %s`` guard so two concurrent advances cannot double-step
    or clobber a writer racing between the SELECT and UPDATE.
    """
    _validate_order_id(order_id)
    db = _db(request)
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT fulfilment_status FROM ops_order_fulfilment WHERE id = %s::uuid FOR UPDATE",
            (order_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("Order not found.")
        current_status = row[0] or ""
        next_status = _STATE_MACHINE.get(current_status)
        if next_status is None:
            if current_status == "ACTIVATED":
                err = DomainError("Order is already in terminal state 'ACTIVATED'.")
                err.code = "ILLEGAL_TRANSITION"
                err.http_status = 400
            else:
                err = DomainError(f"Order is in an unknown state '{current_status}'; cannot advance.")
                err.code = "UNKNOWN_STATE"
                err.http_status = 409
            raise err
        await conn.execute(
            """
            UPDATE ops_order_fulfilment
               SET fulfilment_status = %s,
                   modified_at = NOW()
             WHERE id = %s::uuid AND fulfilment_status = %s
            """,
            (next_status, order_id, current_status),
        )
    logger.info("simulator advance order_id=%s %s→%s", order_id, current_status, next_status)
    return JSONResponse(
        status_code=200,
        content=success_envelope(
            {"order_id": order_id, "previous_status": current_status, "status": next_status},
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ),
    )


__all__ = [
    "ActivateRequest",
    "ConnectionManager",
    "connection_manager",
    "notification_connection_manager",
    "router",
    "to_notification_broadcast",
    "ws_router",
]
