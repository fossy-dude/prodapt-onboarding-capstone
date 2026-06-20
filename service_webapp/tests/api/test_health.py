"""API tests for health/ready endpoints and the OTEL trace contract (AC #2-#6)."""

from __future__ import annotations

import re

from httpx import ASGITransport, AsyncClient

from adapters.postgres import Psycopg3AsyncAdapter
from adapters.redis import ValkeyAdapter

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# A W3C traceparent with a known trace id to assert propagation against.
_INBOUND_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
_INBOUND_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


async def test_health_returns_ok(client: AsyncClient) -> None:
    """``GET /health`` → 200 ``{"status": "ok"}`` (AC #3)."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_response_carries_trace_id_header(client: AsyncClient) -> None:
    """Every response carries an ``X-Trace-Id`` header (AC #6)."""
    resp = await client.get("/health")
    assert _TRACE_ID_RE.match(resp.headers["X-Trace-Id"])


async def test_new_trace_id_when_no_traceparent(client: AsyncClient) -> None:
    """No inbound ``traceparent`` → a fresh non-zero root trace id (AC #5, #6)."""
    resp = await client.get("/health")
    trace_id = resp.headers["X-Trace-Id"]
    assert _TRACE_ID_RE.match(trace_id)
    assert trace_id != "0" * 32  # real span, not an invalid/zero context


async def test_inbound_traceparent_is_propagated(client: AsyncClient) -> None:
    """An inbound ``traceparent`` → same trace id echoed back (AC #5)."""
    resp = await client.get("/health", headers={"traceparent": _INBOUND_TRACEPARENT})
    assert resp.status_code == 200
    assert resp.headers["X-Trace-Id"] == _INBOUND_TRACE_ID


async def test_ready_returns_503_when_deps_down() -> None:
    """``/ready`` → 503 with the standard error envelope when a dep is down (AC #4)."""
    from main import create_app

    # Adapters pointed at a guaranteed-closed port → ping() returns False fast.
    dead_db = Psycopg3AsyncAdapter("host=127.0.0.1 port=1 dbname=x user=x password=x")
    dead_cache = ValkeyAdapter("redis://127.0.0.1:1/0")
    app = create_app(db_adapter=dead_db, cache_adapter=dead_cache)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "NOT_READY"
    assert body["error"]["detail"] == {"postgres": False, "valkey": False}
    # The envelope carries the request's trace id + an ISO timestamp.
    assert body["meta"]["trace_id"] == resp.headers["X-Trace-Id"]
    assert "T" in body["meta"]["timestamp"]
