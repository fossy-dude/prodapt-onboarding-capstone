---
baseline_commit: 31f5d58d1c0552dbc7b0989bdcf7731f4fdca0df
---

# Story 2.8: CDR Simulator UI — Form, Dispatch & WebSocket Trace Display

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer or admin**,
I want a UI to generate synthetic CDR events and watch the end-to-end trace logs update in real time,
so that I can verify pipeline behaviour without needing external tooling.

## Acceptance Criteria

1. **Given** a user with role **`dev`** is on `/simulator/cdr`, **When** they fill in the CDR parameter form (subscriber MSISDN, event type, duration/data MB, timestamp) and click Dispatch, **Then** `POST /api/v1/simulator/cdr` publishes **one** CDR event to `cdr.raw` with a fresh `trace_id`. (FR-68)
2. **And** the WebSocket at `ws://localhost:8000/ws/simulator/trace` streams pipeline stage updates in order: **Received → Deduped → Balance Deducted → Notification Queued**.
3. **And** each pipeline stage update includes: **stage name, timestamp, trace_id, and any error** if applicable. (NFR-15)
4. **And** **100%** of dispatched events must appear in the trace stream. (NFR-15)
5. **And** the `CdrSimulator.tsx` component lives in the simulator portal directory.

## Tasks / Subtasks

- [x] **Task 1: Backend CDR dispatch endpoint** (AC: #1)
  - [x] Add `POST /api/v1/simulator/cdr` to `service_webapp/src/routers/simulator.py` (extend the existing router; do not create a second one). Guard with `require_role("dev")` (see role note). All `async def`. [Source: service_webapp/src/routers/simulator.py:24 (APIRouter prefix=/api/v1/simulator), :43-86 (advance_order pattern)]
  - [x] Build the **`EventEnvelope`** in `service_webapp` with the **identical** field set + dual-trace rule as `cdr-pipeline/src/models/envelope.py`: `{event_type, event_id (UUIDv7), trace_id, timestamp(UTC ISO-8601), payload}`; `traceparent` in the Kafka **header** AND `trace_id` in the **body**. This is the first Kafka producer in `service_webapp` — `aiokafka>=0.11` + `uuid7>=0.1` are already deps. Define a `service_webapp/src/models/envelope.py` that mirrors the cdr-pipeline model byte-for-byte and flag the duplication in Completion Notes. [Source: 2-1 story (EventEnvelope canonical def, dual-trace NFR-17); architecture.md#1.5.1 (two-codebase, no shared pkg), #1.11.4 (ARCH-11)]
  - [x] Build the CDR `payload` to match `cdr-pipeline/src/models/cdr.py` / the `billing_cdr_events` columns: core (`cdr_id`, `session_id`, `subscriber_id`, `cdr_type ∈ {voice,sms,data}`, `telecom_circle`, `cell_tower_id`, `roaming`, `cost_paise`, `status='pending'`, `fraud_flag=false`, `start_time`, `end_time`) + the type-specific block (voice `duration_seconds`/`call_direction`; data `volume_mb`/`network_type`; sms `message_direction`). Publish to **`cdr.raw`** with **key = `subscriber_id`** (per-subscriber ordering). [Source: 2-1 story (cdr.raw key=subscriber_id); service_webapp/db/migrations/V1__baseline_schema.sql:175-209 (CDR columns), 14-31 (enums)]
  - [x] Generate a **fresh `trace_id`** per dispatch (W3C 32-hex). The OTEL middleware already sets `request.state.trace_id` — **reuse it** rather than minting a second id, so the trace is continuous across the HTTP span → Kafka → cdr-pipeline consumer. Return it in the standard success envelope. [Source: service_webapp/src/core/middleware.py (request.state.trace_id); 2-1 story (trace_id continuity)]
  - [x] Wrap with `success_envelope(data, trace_id=getattr(request.state, "trace_id", "unknown"))` (§1.11.3). [Source: service_webapp/src/core/responses.py:21-23]
- [x] **Task 2: Kafka producer wiring in lifespan** (AC: #1, #2)
  - [x] In `service_webapp/src/main.py` lifespan, construct an `AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers, value_serializer=<json utf-8>)`, `start()` it, store on `app.state.kafka_producer`, and `stop()` on shutdown (mirror the owned-adapter pattern). `settings.kafka_brokers` is a comma-joined string — split on `,`. [Source: service_webapp/src/main.py:62-95 (lifespan, owned adapters); src/core/config.py (kafka_brokers); 2-1 story (kafka_brokers split); deferred-work D-similar (kafka_brokers is csv string)]
- [x] **Task 3: WebSocket trace stream + broadcaster** (AC: #2, #3, #4)
  - [x] Add `@router.websocket("/ws/simulator/trace")` to the simulator router. A `ConnectionManager` tracks connected WS clients (accept/`add`, `discard`, `broadcast`). [Source: epics.md#Story-2.8 (line 1072); architecture.md#1.9.2 (WebSocket trace, FR-68)]
  - [x] **How stages get emitted (pick one + document):** the pipeline stages (Received/Deduped/Balance Deducted/Notification Queued) happen **inside cdr-pipeline**, a separate process. `service_webapp` cannot see them directly. Two viable designs —
    - *(A) Trace event topic:* cdr-pipeline (Stories 2.2/2.3/2.4) publishes a stage event per CDR to a `simulator.trace` topic (key=`trace_id`); `service_webapp` runs an `AIOKafkaConsumer` (group `simulator-trace-broadcaster`) on startup that fans each message to connected WS clients. **Requires cross-story agreement with 2.2/2.3/2.4** to emit the events — note the dependency.
    - *(B) In-process broadcast:* for MVP the simulator publishes stage updates itself (e.g. it emits "Received" on dispatch, and a lightweight cdr-pipeline hook emits the rest). Less faithful but ships without touching the consumer.
    - Prefer **(A)** for the 100%-of-events guarantee (AC #4); if 2.2–2.4 are not emitting trace events yet, implement (A)'s consumer + a stub producer contract and **flag the cross-story dependency in Completion Notes** so 2.2/2.3/2.4 emit the four stage events. Either way the WS message shape is fixed: `{stage, timestamp, trace_id, error}`. [Source: epics.md#Story-2.8 (lines 1072-1076, NFR-15); architecture.md#1.9.2, #1.11.4]
  - [x] Auth on the WS: require the same `dev` role (validate the JWT from a query param / first message, matching how the portal authenticates). Document the chosen token-passing method.
- [x] **Task 4: Frontend CDR Simulator page** (AC: #1, #5)
  - [x] Create `frontend/src/portals/simulator/CdrSimulator.tsx` (named export, `readonly` `Props`, TailwindCSS only — per `frontend/CLAUDE.md`). Form fields: subscriber MSISDN, `cdr_type` (voice/data/sms), duration_seconds (voice) / volume_mb (data) / message_direction (sms), timestamp. Dispatch button → `apiClient.post('/simulator/cdr', ...)`. [Source: frontend/CLAUDE.md; frontend/src/lib/api.ts (apiClient); epics.md#Story-2.8 (line 1078)]
  - [x] Wire the route in `frontend/src/App.tsx` under the existing `/simulator/*` `<RoleGuard allowedRoles={['dev']}>` block: add `<Route path="cdr" element={<CdrSimulator />} />`. [Source: frontend/src/App.tsx (/simulator/* RoleGuard 'dev')]
- [x] **Task 5: Frontend WebSocket trace display** (AC: #2, #3)
  - [x] Add a `useTraceWebSocket` hook (`frontend/src/hooks/useTraceWebSocket.ts`, camelCase) connecting to `ws://localhost:8000/ws/simulator/trace`, parsing `{stage, timestamp, trace_id, error}` into an ordered list. Render the four-stage progression per `trace_id` in `CdrSimulator.tsx`; surface any `error`. Reconnect on close. [Source: epics.md#Story-2.8 (lines 1072-1076); frontend/CLAUDE.md (hooks naming)]
- [x] **Task 6: Tests** (AC: #1, #2, #3, #4)
  - [x] Backend unit (httpx.AsyncClient + mocked producer + mocked JWTValidator-style `require_role`): `dev` token → 201 and a publish to `cdr.raw` with correct envelope (header `traceparent` + body `trace_id` equal, key=`subscriber_id`); missing/non-dev token → 401/403. Assert CDR payload validates against the cdr-pipeline `cdr.py` schema. [Source: 1-8 story (auth matrix); 2-1 story (envelope contract)]
  - [x] Backend unit: WS `ConnectionManager` connect/disconnect/broadcast; the `simulator.trace` consumer fans a message to connected clients (mock consumer). [Source: service_webapp test conventions]
  - [x] Integration (`@pytest.mark.slow`, testcontainers Redpanda, rootless podman): `POST /simulator/cdr` publishes to `cdr.raw` (assert message present, key correct, partition sane); a `simulator.trace` message reaches the WS client end-to-end. [Source: 1-4 story (testcontainers); 2-1 story (slow integration)]
  - [x] Frontend: Vitest + RTL for `CdrSimulator.tsx` (form → POST mocked, trace list rendering, error state) and the WS hook (mock WebSocket). [Source: frontend/CLAUDE.md (Vitest+RTL)]

## Dev Notes

### Scope boundary

- **DOES:** the `/api/v1/simulator/cdr` dispatch endpoint (envelope, dual-trace, publish to `cdr.raw`), the Kafka producer in `service_webapp` lifespan, the `/ws/simulator/trace` WS + `ConnectionManager` + the trace-event consumer/broadcaster, the `CdrSimulator.tsx` page + WS hook + route, unit + integration tests.
- **DOES NOT:** build the cdr-pipeline **consumer**, dedup, balance, or audit logic (2.2/2.3/2.4) — but **depends on those stories emitting the four trace stage events** for AC #2/#4 (see Task 3). Does not build the SIM-activation simulator or Notification Portal (2.9).

### 🚨 Two variances vs the epic text — follow the CODEBASE, not the epic

1. **Role is `dev`, not `admin`.** The epic AC says "role = 'admin'", but `service_webapp/src/routers/simulator.py` (Story 1.7) and `frontend/src/App.tsx` both gate the simulator portal on **`dev`** (`cognito:groups` contains `dev`). Use `dev` for the POST + WS + route guard, and note the epic/codebase discrepancy in Completion Notes. (Valid Cognito groups: `subscriber, ops, fraud, dev, admin, marketing`.) [Source: service_webapp/src/routers/simulator.py:47 (require_role("dev")); frontend/src/App.tsx (/simulator/* RoleGuard 'dev'); 1-8 story (cognito:groups)]
2. **Frontend path is `portals/simulator/`, not `pages/simulator/`.** The epic says `frontend/src/pages/simulator/`, but the repo uses FSD `portals/` (Story 1.7's `SimActivation.tsx` lives in `frontend/src/portals/simulator/`). Put `CdrSimulator.tsx` there. [Source: frontend/src/portals/simulator/SimActivation.tsx; frontend/CLAUDE.md]

### Envelope is shared by contract, not by import (two-codebase rule)

- `service_webapp` and `cdr-pipeline` are separate codebases with **no shared package** — they communicate only via Kafka + Postgres. The CDR produced here must be byte-compatible with what `cdr-pipeline/src/models/{envelope,cdr}.py` (Story 2.1) validates. Mirror the field set exactly; **flag the duplication** so a future shared module can consolidate. [Source: architecture.md#1.5.1 (two-codebase, no shared pkg); 2-1 story (canonical envelope)]

### Trace continuity is the high-value requirement

- `trace_id` must be the same from the HTTP request → Kafka `cdr.raw` header/body → cdr-pipeline spans → audit row (2.4). Reuse `request.state.trace_id` (set by the OTEL middleware) as the envelope `trace_id`; do not generate a second one. The cdr-pipeline consumer will `opentelemetry.propagate.extract(headers)` to continue it. [Source: service_webapp/src/core/middleware.py; 2-1 story (NFR-17 dual trace, extract in consumer); 2-4 story (audit row stores trace_id)]

### Cross-story dependency (AC #2/#4 — do not assume it's free)

- The four stage events (Received/Deduped/Balance Deducted/Notification Queued) originate in **cdr-pipeline** (2.2 emits Received+Deduped, 2.3 Balance Deducted, 2.4/2.9 Notification Queued). If this story lands first, the trace stream can only show "Received" until those stories emit `simulator.trace` events. Implement the broadcaster/consumer + the fixed message shape now, and record the cross-story contract so 2.2/2.3/2.4 emit `{stage, timestamp, trace_id, error}` to the agreed topic. [Source: epics.md#Story-2.8 (lines 1072-1076)]

### Kafka producer is new to service_webapp

- `aiokafka`/`uuid7` are already in `service_webapp/pyproject.toml`, but **no producer has been wired yet** — this is the first. Follow the lifespan owned-adapter idiom; never instantiate a producer per-request. `settings.kafka_brokers` is a comma-joined string: split before passing to `bootstrap_servers`. [Source: service_webapp/pyproject.toml; src/main.py:62-95; deferred-work (kafka_brokers csv string)]

### Config & deps

- No new runtime deps (aiokafka, uuid7, fastapi already present). If `EventEnvelope`/CDR Pydantic models are added under `service_webapp/src/models/`, add to tox env `deps` if import collection requires it. [Source: service_webapp/pyproject.toml; 2-1 story (add imports to tox env deps)]

### Testing standards summary

- Backend: `uv tox` `lint`/`test`; httpx.AsyncClient API tests with mocked producer + role matrix (401/403/201); one `slow` testcontainers Redpanda integration (publish + WS fan-out). Frontend: `npm run test` (Vitest + RTL), `npm run typecheck`, `npm run lint`. Add new imports to tox env `deps`. [Source: service_webapp/pyproject.toml; frontend/package.json; 1-4 story (testcontainers); 1-8 story (auth matrix)]

### Project Structure Notes

- **NEW:** `service_webapp/src/models/envelope.py` (+ `cdr.py` if not present), `service_webapp/src/routers/simulator.py` gains `POST /cdr` + `WS /ws/simulator/trace` + a `ConnectionManager`/broadcaster (e.g. `src/notifications/` or `src/simulator/`), `frontend/src/portals/simulator/CdrSimulator.tsx`, `frontend/src/hooks/useTraceWebSocket.ts`, tests both sides.
- **MODIFIES:** `service_webapp/src/main.py` (lifespan: start/stop `app.state.kafka_producer` + trace consumer), `frontend/src/App.tsx` (`/simulator/cdr` route), `frontend/src/lib/api.ts` (add `POST /simulator/cdr` helper).
- **Variances flagged:** role `dev` (not `admin`); frontend `portals/simulator/` (not `pages/simulator/`).

### References

- [Source: epics.md#Story-2.8 (lines 1056-1078)]
- [Source: architecture.md#1.9.2 (WebSocket trace FR-68), #1.11.4 (envelope ARCH-11, dual trace), #1.4.1 (CDR data flow), #1.5.1 (two-codebase), #1.8.1-1.8.2 (cognito:groups, dev role)]
- [Source: service_webapp/src/routers/simulator.py:24,43-86 (router + advance pattern, require_role('dev')), src/core/middleware.py (request.state.trace_id), src/core/responses.py:21-23, src/main.py:62-95 (lifespan)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:14-31 (enums), 175-209 (CDR columns)]
- [Source: frontend/src/App.tsx (/simulator/* RoleGuard 'dev'), src/lib/api.ts (apiClient), src/portals/simulator/SimActivation.tsx, frontend/CLAUDE.md]
- [Source: 2-1 story (envelope, cdr.raw key=subscriber_id, dual trace, UUIDv7), 2-2/2-3/2-4 stories (must emit trace stage events), 1-7 story (simulator router), 1-8 story (cognito:groups auth matrix), 1-4 story (testcontainers)]

## Dev Agent Record

### Agent Model Used
GLM-5.2 (Claude Code)

### Debug Log References
- Backend unit suite: `cd service_webapp && just test` — 15/15 new `test_cdr_dispatch_endpoint.py` tests pass; 2 integration tests in `test_cdr_dispatch_integration.py` correctly skip by default (require `--run-slow`/`--run-integration` + container runtime).
- Frontend suite: `cd frontend && npx vitest run` — 12/12 new tests pass (`useTraceWebSocket.test.ts` ×5, `CdrSimulator.test.tsx` ×7).
- Lint: `just lint` (backend) and `npm run lint` (frontend) clean for all Story 2.8 files; remaining lint/typecheck failures are pre-existing in `account.py`, `test_payment_methods.py`, `PaymentMethods.test.tsx`, `Profile.test.tsx` (untouched by this story).

### Completion Notes List

**Implementation summary**
- **Backend dispatch (Task 1):** Added `POST /api/v1/simulator/cdr` to the existing simulator router (no second router). Guards with `require_role("dev")`. Builds a `CdrDispatchRequest` → CDR payload dict validated against the cdr-pipeline `CdrEvent` discriminated union (via `TypeAdapter`), wraps it in `EventEnvelope`, and publishes to `cdr.raw` with `key=subscriber_id` and a dual-trace `traceparent` header (NFR-17). `trace_id` is reused from `request.state.trace_id` (OTEL middleware) for end-to-end continuity. Wrapped with `success_envelope`. No new runtime deps (`aiokafka`, `uuid7` already in `pyproject.toml`).
- **Envelope/CDR models (Task 1):** Created `service_webapp/src/models/envelope.py` + `cdr.py` mirroring `cdr-pipeline/src/models/{envelope,cdr}.py` **byte-for-byte** (same field set, validators, serializers, discriminated union). **DUPLICATION FLAGGED** per the two-codebase rule (architecture §1.5.1, ARCH-11) — these must be kept in sync by contract until a future shared module consolidates them.
- **Kafka producer in lifespan (Task 2):** Wired `AIOKafkaProducer` into `main.py` lifespan following the owned-adapter idiom — `kafka_brokers` CSV string is split on `,`; producer `start()`ed on startup, `stop()`ed on shutdown; stored on `app.state.kafka_producer`. `create_app` now accepts injectable `kafka_producer`/`trace_consumer` for tests.
- **WebSocket + broadcaster (Task 3):** Chose design **(A)** — the trace-event topic. Added `WS /ws/simulator/trace` + a `ConnectionManager` (connect/disconnect/broadcast with broken-client pruning). A background `AIOKafkaConsumer` (group `simulator-trace-broadcaster`, topic `simulator.trace`, `auto_offset_reset=latest`) is started in lifespan and fans each message to connected WS clients. Fixed message shape `{stage, timestamp, trace_id, error}`. WS auth: JWT passed as `?token=<bearer>` query param, validated by `jwt_validator.decode` + `dev` group check (closes with 4001/4003 on failure). Reconnect handled client-side (frontend hook).
- **Cross-story dependency (AC #2/#4):** The four pipeline stages (Received/Deduped/Balance Deducted/Notification Queued) originate in **cdr-pipeline**. This story implements the full broadcaster/consumer + fixed contract now, but the trace stream will only show stages once Stories **2.2/2.3/2.4** emit `{stage, timestamp, trace_id, error}` to `simulator.trace`. Contract recorded here so the consumer stories can conform.
- **Frontend page (Task 4):** Created `frontend/src/portals/simulator/CdrSimulator.tsx` (named export, TailwindCSS only, FSD `portals/simulator/` path). Form: MSISDN, `cdr_type` (voice/data/sms), type-conditional fields (duration_seconds/volume_mb/message_direction), timestamp. Dispatch via `dispatchCdr` helper → `apiClient.post('/simulator/cdr')`. Route wired in `App.tsx` under the existing `dev` `RoleGuard`.
- **Frontend WS hook (Task 5):** Created `useTraceWebSocket.ts` (camelCase) connecting to `ws://localhost:8000/ws/simulator/trace?token=...`, parsing `{stage,timestamp,trace_id,error}` into an ordered list, with reconnect-on-close and a `status` indicator. `CdrSimulator` renders the four-stage progression filtered by the dispatched `trace_id` and surfaces any `error`.
- **Tests (Task 6):** 15 backend unit tests (201 + publish to cdr.raw, dual-trace header==body equality, key==subscriber_id, payload validates `CdrEvent`, 401 no-auth, 403 wrong-role, 503 no-producer, ConnectionManager connect/disconnect/broadcast/prune, trace fan-out) + 2 slow integration tests (Redpanda testcontainers). 12 frontend tests (form rendering, dispatch POST, conditional fields per type, success trace-id, streamed stages, error surfacing, WS hook connection/message-order/clear/no-token).

**Variances vs epic (flagged per Dev Notes)**
1. Role is `dev`, not `admin` — matches the codebase (`require_role("dev")` in simulator router + `RoleGuard allowedRoles={['dev']}` in `App.tsx`). Epic AC text said `admin`; followed the codebase.
2. Frontend path is `portals/simulator/`, not `pages/simulator/` — matches the FSD layout (`SimActivation.tsx` lives there).

**Deferred / not done**
- Full end-to-end trace stream (all four stages) depends on cdr-pipeline Stories 2.2/2.3/2.4 emitting `simulator.trace` events. The slow integration test exercises publish-to-`cdr.raw` and the WS fan-out with a directly-published `simulator.trace` message; it does not exercise the live cdr-pipeline consumer chain (those stories are `in-progress`).
- `aiokafka` was missing from the tox `test` env `deps`; added it (+ `boto3`, which was also needed by the app import graph) to `pyproject.toml`.

### File List
**New:**
- `service_webapp/src/models/__init__.py`
- `service_webapp/src/models/envelope.py`
- `service_webapp/src/models/cdr.py`
- `service_webapp/tests/unit/test_cdr_dispatch_endpoint.py`
- `service_webapp/tests/integration/test_cdr_dispatch_integration.py`
- `frontend/src/portals/simulator/CdrSimulator.tsx`
- `frontend/src/portals/simulator/CdrSimulator.test.tsx`
- `frontend/src/hooks/useTraceWebSocket.ts`
- `frontend/src/hooks/useTraceWebSocket.test.ts`
**Modified:**
- `service_webapp/src/routers/simulator.py` (POST /cdr, WS /ws/simulator/trace, ConnectionManager, connection_manager)
- `service_webapp/src/main.py` (lifespan: kafka_producer + trace consumer/broadcaster; create_app injection params)
- `service_webapp/pyproject.toml` (tox `test` env: +aiokafka, +boto3)
- `frontend/src/App.tsx` (/simulator/cdr route)
- `frontend/src/lib/api.ts` (dispatchCdr helper + CdrDispatchPayload type)

## Change Log
- 2026-06-23: Story 2.8 implemented — backend CDR dispatch endpoint + Kafka producer + WebSocket trace broadcaster (consumer on `simulator.trace`), `EventEnvelope`/`CdrEvent` mirror models, frontend `CdrSimulator` page + `useTraceWebSocket` hook + route, 27 new tests (15 backend unit + 2 backend slow integration + 12 frontend). Status: ready-for-dev → review.
