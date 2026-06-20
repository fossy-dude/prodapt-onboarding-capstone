"""Unit test: OTEL span attributes never carry PII (AC #7, NFR-16, ARCH-32).

Attaches an in-memory span exporter to the app's tracer provider, issues a request
whose query string deliberately carries a phone-number-looking value, and asserts
the recorded span attributes contain only method + path — never the raw URL or the
PII payload.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Substring that must NEVER appear in any span attribute (PII stand-in).
_PII_MARKER = "9876543210"


async def test_no_pii_in_span_attributes() -> None:
    """Span attributes are method + path only; query-string PII is excluded (AC #7)."""
    from main import create_app

    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # PII smuggled in via the query string — must not reach span attributes.
        await ac.get("/health", params={"msisdn": _PII_MARKER})

    spans = exporter.get_finished_spans()
    assert spans, "expected at least one http_request span to be recorded"
    request_spans = [s for s in spans if s.name == "http_request"]
    assert request_spans, "expected an 'http_request' span"

    for span in request_spans:
        attrs = dict(span.attributes)
        # Only safe attributes are permitted.
        assert set(attrs) <= {"http.method", "http.url.path"}, f"unexpected attrs: {set(attrs)}"
        # Path only — the query string (and its PII) must be absent.
        assert attrs.get("http.method") == "GET"
        assert attrs.get("http.url.path") == "/health"
        for value in attrs.values():
            assert _PII_MARKER not in str(value), f"PII leaked into span attribute: {attrs}"
