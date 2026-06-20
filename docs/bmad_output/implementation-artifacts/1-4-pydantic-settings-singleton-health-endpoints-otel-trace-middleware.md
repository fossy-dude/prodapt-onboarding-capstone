# Story 1.4: pydantic-settings Singleton, Health Endpoints & OTEL Trace Middleware

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want each service to load its configuration exactly once at startup, expose `/health` and `/ready` endpoints, and propagate OTEL trace IDs through every request,
so that misconfigured deployments fail fast at boot and every request is traceable end-to-end.

## Acceptance Criteria

1. **Given** both `cdr-pipeline` and `service_webapp` services exist, **When** either service starts, **Then** a pydantic-settings singleton loads all required env vars at module import time and raises a descriptive error immediately if any required value is missing (ARCH-17).
2. `service_webapp` exposes `GET /health` and `GET /ready`; both respond within 200ms under normal operating conditions (FR-77, NFR-19).
3. `GET /health` returns 200 with `{"status": "ok"}` when the service is running.
4. `GET /ready` returns 200 only when the Postgres connection pool and Valkey connection are healthy; returns 503 otherwise.
5. OTEL trace middleware in FastAPI extracts `traceparent` from incoming request headers; generates a new root span if absent (ARCH-27).
6. `trace_id` is stored in `request.state.trace_id` and returned in the `X-Trace-Id` response header on every response.
7. PII never appears in OTEL span attributes; only subscriber UUID or `MSISDN[-4:]` suffix is used (NFR-16, ARCH-32).

## Tasks / Subtasks

- [ ] **Task 1: Implement the pydantic-settings singleton in `service_webapp`** (AC: #1)
  - [ ] Create `service_webapp/src/core/config.py` with nested `BaseSettings` models (`DatabaseSettings`, plus top-level `Settings`)
  - [ ] Use `SettingsConfigDict(env_nested_delimiter="__", env_file=".env", secrets_dir="/run/secrets")`
  - [ ] Instantiate `settings = Settings()` at module import (eager load) — missing required values raise immediately with a descriptive error
  - [ ] Export as `from core.config import settings` (single singleton per service)
  - [ ] Bootstrap from the reference template `fossy-dude/pydantic-config-mgmt-template` (do not reinvent the pattern)
- [ ] **Task 2: Implement the pydantic-settings singleton in `cdr-pipeline`** (AC: #1)
  - [ ] Create `cdr-pipeline/src/core/config.py` with the same eager-load pattern, scoped to the env vars the consumer needs (DB, Redis, Kafka)
  - [ ] cdr-pipeline has no HTTP health endpoints in this story (its management API is Epic 2) — only the config singleton is required here
- [ ] **Task 3: Implement the OTEL trace middleware** (AC: #5, #6, #7)
  - [ ] Create `service_webapp/src/core/middleware.py` with `OtelTraceMiddleware(BaseHTTPMiddleware)` (see Dev Notes for the exact reference implementation)
  - [ ] Extract `traceparent` via `opentelemetry.propagate.extract(dict(request.headers))`; start a span (new root if absent)
  - [ ] Store `trace_id` in `request.state.trace_id`; set `X-Trace-Id` response header on every response
  - [ ] Set only safe span attributes (method, url path) — NEVER PII; if MSISDN must appear, use `[-4:]` suffix only
- [ ] **Task 4: Implement health/ready endpoints** (AC: #2, #3, #4)
  - [ ] Create `service_webapp/src/routers/health.py` with `GET /health` → `{"status": "ok"}` (200) and `GET /ready`
  - [ ] `/ready` checks Postgres pool + Valkey connectivity; 200 only if both healthy, else 503 with the standard error envelope
  - [ ] Health endpoints must NOT require auth and must be cheap (< 200ms)
- [ ] **Task 5: Wire up the FastAPI app entrypoint** (AC: #1, #2, #5, #6)
  - [ ] Create/extend `service_webapp/src/main.py` — instantiate FastAPI app, register `OtelTraceMiddleware`, include the health router
  - [ ] Ensure `from core.config import settings` is imported so config eager-loads at boot (fail-fast)
  - [ ] App must serve on port 8000 (per README verify step `curl http://localhost:8000/health`)
- [ ] **Task 6: Adapters/protocols stub for the readiness check** (AC: #4)
  - [ ] If not already present, add minimal `core/protocols/db.py` (DatabaseProtocol) and `core/protocols/cache.py` (CacheProtocol), plus thin `adapters/postgres.py` (Psycopg3 AsyncConnectionPool) and `adapters/redis.py` (valkey async) — only enough for `/ready` to ping each. Full adapters are fleshed out in later domain stories; do not over-build.
- [ ] **Task 7: Tests** (AC: #1–7)
  - [ ] Unit test: missing required env var → `Settings()` raises a descriptive error
  - [ ] API test (httpx.AsyncClient): `/health` → 200 `{"status":"ok"}`; response carries `X-Trace-Id` header
  - [ ] API test: request with an inbound `traceparent` header → same trace context propagated; `X-Trace-Id` returned
  - [ ] API test: `/ready` → 200 when deps healthy (testcontainers Postgres + Valkey), 503 when a dep is down
  - [ ] Assert no PII in span attributes (only method/path/subscriber-UUID-style values)

## Dev Notes

### Scope boundary

- **DOES:** config singleton (both codebases), OTEL trace middleware, `/health` + `/ready`, FastAPI app entrypoint, minimal protocols/adapters needed for the readiness ping.
- **DOES NOT:** Implement auth (Story 1.8), domain routers (account/balance/etc.), LangFuse instrumentation (Story 1.5 — separate decorator), or the full adapter suite. Keep adapters minimal — just enough for `/ready`.
- This is the **first application-code story** in the repo. It establishes `service_webapp/src/` structure that every later story builds on. Get the layout right.

### RESOLVED directory decision

- Backend = `service_webapp/`. The architecture's `core/middleware.py`, `core/config.py`, `routers/health.py` all live under `service_webapp/src/`. [user decision 2026-06-19]
- The existing `service_webapp/main.py` (a trivial `print` stub at the package root) is NOT the FastAPI app. The real app entrypoint is `service_webapp/src/main.py` per architecture §1.12.1. Move/replace accordingly and update any references (the justfile `backend` recipe runs `uvicorn src.main:app`). Confirm `pyproject.toml`'s `[tool.pytest] pythonpath`/ruff `src` settings point at `src`.

### pydantic-settings pattern (architecture §1.11.1 — follow exactly)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str

class Settings(BaseSettings):
    db: DatabaseSettings
    redis_url: str
    kafka_brokers: str
    azure_openai_api_key: str
    langfuse_secret_key: str
    # ... all other config

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",   # DB__HOST → db.host
        env_file=".env",
        secrets_dir="/run/secrets",  # Podman secrets mount (MVP)
    )

settings = Settings()   # loaded once at import; fails fast on missing values
```

Rules:
- One `Settings` singleton per service; import as `from core.config import settings`.
- No hard-coded config anywhere; all via `settings.*`.
- Secrets Manager source is Target-State only; MVP uses `.env` + env vars.
- The env keys must match the `.env.example` authored in Story 1.3 (e.g. `DB__HOST`, `REDIS_URL`, `KAFKA_BROKERS`, `LANGFUSE_SECRET_KEY`). Keep them in sync; a key here with no `.env.example` placeholder will fail-fast in CI/onboarding.

[Source: architecture.md#1.11.1 (lines 722–764)]

### OTEL trace middleware (architecture §1.12.2 — reference implementation)

```python
# core/middleware.py
from opentelemetry import trace
from opentelemetry.propagate import extract
from starlette.middleware.base import BaseHTTPMiddleware

class OtelTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        ctx = extract(dict(request.headers))                 # traceparent in → context
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("http_request", context=ctx) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))  # ⚠ ensure no PII in query string
            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
```

PII hygiene (NFR-16, ARCH-32, §1.11.6):
- Never put MSISDN, name, address, or card data in span attributes. Use subscriber UUID or `msisdn[-4:]`.
- `http.url` can leak PII if query params carry it — be mindful; prefer logging the route template/path over the full URL with query string. This is a likely review finding if left as raw `str(request.url)`.

Dependencies (already in `service_webapp/pyproject.toml`): `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`. Consider using the FastAPI instrumentation for automatic spans, but the custom middleware is the one that owns `request.state.trace_id` + `X-Trace-Id` — keep the custom middleware as the source of truth for the trace_id contract.

[Source: architecture.md#1.12.2 (lines 1237–1258); #1.11.6 (lines 938–943); #1.13.7 (line 1605)]

### Health/ready contract

- `/health` (liveness): 200 `{"status": "ok"}`, no dependency checks, no auth, instant.
- `/ready` (readiness): pings Postgres pool + Valkey; 200 only if both healthy; 503 otherwise. Use the standard error envelope on 503:
  ```json
  {"error": {"code": "NOT_READY", "message": "...", "detail": {...}}, "meta": {"trace_id": "...", "timestamp": "..."}}
  ```
- Both must respond < 200ms (NFR-19). Don't do heavy work in `/ready`; a `SELECT 1` and a Valkey `PING` suffice.
- Architecture README verify step expects `/health` on port 8000 (service_webapp) and 8001 (cdr-pipeline management API — Epic 2, not this story).

[Source: architecture.md#1.11.3 (API envelope, lines 825–847); epics.md#Story-1.4; #1.15.1 (verify, lines 1791–1794)]

### Async-only rule

- Every FastAPI route is `async def`. All I/O is async: `psycopg` async with `AsyncConnectionPool`, `valkey` async client. No blocking I/O in routes. [Source: architecture.md#1.12.1 (Async-only principle, line 990)]

### Dependency Inversion (protocols)

- Business logic depends on `Protocol` interfaces in `core/protocols/`, never the concrete library. For this story, define `DatabaseProtocol` and `CacheProtocol` minimally and have `/ready` depend on the protocol; the concrete `Psycopg3AsyncAdapter` / `RedisAdapter` implement them. This sets the pattern for all later stories — get it right now so later stories follow. [Source: architecture.md#1.12.1 (lines 988, 1040–1049)]

### Testing standards summary

- pytest via `uv tox -e <test-env>`; FastAPI tested with `httpx.AsyncClient`. Do NOT mock Postgres — use `testcontainers` (Postgres + Valkey/redis) for the `/ready` integration test. [Source: architecture.md#1.11.8 (lines 972–978)]
- Tests live in `service_webapp/tests/` (`unit/`, `integration/`, `conftest.py` with testcontainers fixtures). [Source: architecture.md#1.12.1 (lines 1127–1130)]
- The config-fail-fast test should manipulate env (e.g. monkeypatch/clear a required var) and assert `Settings()` raises — this is a unit test, no containers needed.
- `LANGFUSE_ENABLED=false` should let tests run without a live LangFuse (relevant to Story 1.5, but keep this in mind so config defaults don't force a LangFuse connection at import). [Source: epics.md#Story-1.5]

### Project Structure Notes

- New files: `service_webapp/src/core/config.py`, `service_webapp/src/core/middleware.py`, `service_webapp/src/routers/health.py`, `service_webapp/src/main.py`, minimal `core/protocols/{db,cache}.py` + `adapters/{postgres,redis}.py`.
- `cdr-pipeline/src/core/config.py` for the consumer config singleton.
- Replace the placeholder `service_webapp/main.py` print-stub; ensure the package entrypoint is `src.main:app`.
- Variance: architecture sometimes writes config example without explicit nested env mapping for `redis_url`/`kafka_brokers` (flat strings). Keep `db` nested (`DB__HOST`) and the rest flat (`REDIS_URL`, `KAFKA_BROKERS`) to match the `.env.example` from Story 1.3.

### References

- [Source: epics.md#Story-1.4 (lines 362–378)]
- [Source: architecture.md#1.11.1-Configuration-Management (lines 722–764)]
- [Source: architecture.md#1.11.3-API-Response-Format (lines 825–847)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (core/, routers/, adapters/, lines 1034–1060)]
- [Source: architecture.md#1.12.2 (OTEL middleware, lines 1237–1258)]
- [Source: architecture.md#1.11.8-Testing-Patterns (lines 972–978)]
- [Source: https://github.com/fossy-dude/pydantic-config-mgmt-template — bootstrap template]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
