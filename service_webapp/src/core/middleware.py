"""OpenTelemetry trace-context middleware (Story 1.4; architecture §1.12.2).

Owns the trace-id contract for every request: extracts an inbound W3C
``traceparent`` (or starts a fresh root span when absent), stashes the ``trace_id``
on ``request.state.trace_id`` and echoes it back via the ``X-Trace-Id`` response
header. The custom middleware — not the FastAPI auto-instrumentation — is the
source of truth for this contract (architecture §1.13.7).

PII hygiene (NFR-16, ARCH-32, §1.11.6): span attributes carry only ``http.method``
and the URL **path** (never the raw URL with query string, which can leak PII).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from opentelemetry import trace
from opentelemetry.propagate import extract
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agents.support.identity import support_context
from core.auth import _extract_token
from core.errors import UnauthenticatedError
from db.billing.queries import get_msisdn_for_subscriber

logger = logging.getLogger(__name__)

# Safe span attributes — method + path template only. NEVER PII: no MSISDN, name,
# address or card data; subscriber UUID or ``msisdn[-4:]`` only, when required.
_ATTR_HTTP_METHOD = "http.method"
# Path only — deliberately excludes the query string (architecture §1.11.6 review
# finding: ``str(request.url)`` can leak PII carried in query params).
_ATTR_HTTP_PATH = "http.url.path"

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]

# CopilotKit runtime mount prefix (Story 5.4; routers/chat.py CHAT_ENDPOINT_PREFIX).
# Requests under here are authenticated + identity-bound for the Support Agent.
_CHAT_PREFIX = "/api/chat"
# Frontend→backend chat conversation id (CopilotKit forwards provider ``headers``).
_SESSION_ID_HEADER = "x-chat-session-id"


class OtelTraceMiddleware(BaseHTTPMiddleware):
    """Propagate OTEL trace context and stamp ``X-Trace-Id`` on every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Extract/propagate trace context, set ``request.state.trace_id`` + response header."""
        # Inbound traceparent → context; absent → a fresh root span is started below.
        ctx = extract(dict(request.headers))
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("http_request", context=ctx) as span:
            # Safe attributes only (PII hygiene).
            span.set_attribute(_ATTR_HTTP_METHOD, request.method)
            span.set_attribute(_ATTR_HTTP_PATH, request.url.path)

            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id

            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response


class SupportIdentityMiddleware(BaseHTTPMiddleware):
    """Bind authenticated subscriber identity onto Support Agent requests.

    CopilotKit registers an opaque catch-all at ``/api/chat/*`` that we cannot
    attach a FastAPI ``Depends`` to, so this middleware enforces the same Bearer
    JWT contract the REST routers use (``require_role("subscriber")``) for every
    chat request: it decodes the token, takes the subscriber UUID from ``sub``,
    resolves the unmasked MSISDN from the DB, reads the chat session id from the
    ``X-Chat-Session-Id`` header, and binds all three onto the request via
    :func:`agents.support.identity.support_context` so the Support Agent tools can
    scope queries without the LLM ever having to supply identity (Story 5.4 AC #2).

    Non-chat paths and the unauthenticated AG-UI probes are passed through. A
    missing/invalid token on a chat path raises ``UnauthenticatedError`` (→ 401)
    just like the REST guard. The MSISDN lookup is a single PK-indexed row; it
    never appears in logs (ARCH-32).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith(_CHAT_PREFIX):
            return await call_next(request)

        validator = getattr(request.app.state, "jwt_validator", None)
        if validator is None:
            raise RuntimeError("jwt_validator not wired onto app.state — check lifespan")

        token = _extract_token(request)  # raises UnauthenticatedError on a bad header
        payload = validator.decode(token)  # raises UnauthenticatedError on a bad token
        subscriber_id = payload.get("sub")
        if not subscriber_id:
            raise UnauthenticatedError("Access token is missing the 'sub' claim.")

        msisdn = await self._resolve_msisdn(request, str(subscriber_id))
        if msisdn is None:
            raise UnauthenticatedError("Authenticated subscriber has no MSISDN on record.")
        session_id = request.headers.get(_SESSION_ID_HEADER, "")

        with support_context(
            subscriber_id=str(subscriber_id),
            msisdn=msisdn,
            session_id=session_id,
        ):
            return await call_next(request)

    @staticmethod
    async def _resolve_msisdn(request: Request, subscriber_id: str) -> str:
        """Look up the subscriber's unmasked MSISDN (single PK row)."""
        db = getattr(request.app.state, "db_adapter", None)
        if db is None:
            raise RuntimeError("db_adapter not wired onto app.state — check lifespan")
        async with db.transaction() as conn:
            return await get_msisdn_for_subscriber(conn, UUID(subscriber_id))
