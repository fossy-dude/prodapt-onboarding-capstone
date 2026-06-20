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

from collections.abc import Awaitable, Callable

from opentelemetry import trace
from opentelemetry.propagate import extract
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Safe span attributes — method + path template only. NEVER PII: no MSISDN, name,
# address or card data; subscriber UUID or ``msisdn[-4:]`` only, when required.
_ATTR_HTTP_METHOD = "http.method"
# Path only — deliberately excludes the query string (architecture §1.11.6 review
# finding: ``str(request.url)`` can leak PII carried in query params).
_ATTR_HTTP_PATH = "http.url.path"

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


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
