# Story 2.5: CDR Management API — DLQ Inspect & Worker Control

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer or operator**,
I want API endpoints to inspect the dead-letter queue and pause/resume CDR workers,
so that I can diagnose pipeline failures and safely halt processing without restarting containers.

## Acceptance Criteria

1. **Given** events exist in `cdr.dlq`, **When** `GET /api/v1/admin/dlq` is called with a valid admin JWT, **Then** it returns a **paginated** list of DLQ events with: `cdr_id`, `error_reason`, `original_topic`, `failed_at`, and a `raw_payload` preview (PII-masked).
2. **And** `GET /api/v1/admin/dlq/{cdr_id}` returns the full raw payload for a single event.
3. **Given** an operator calls `POST /api/v1/admin/workers/pause`, **When** the request is processed, **Then** all CDR consumer coroutines stop polling new messages within **2 seconds**; the endpoint returns `{ "status": "paused" }`.
4. **And** `POST /api/v1/admin/workers/resume` resumes polling and returns `{ "status": "running" }`.
5. **And** both worker endpoints (and the DLQ endpoints) require role claim = `admin` in the JWT (`cognito:groups` contains `admin`).

## Tasks / Subtasks

- [ ] **Task 1: Management FastAPI app in cdr-pipeline** (AC: all)
  - [ ] Create `cdr-pipeline/src/management/api.py` — a FastAPI `APIRouter(prefix="/api/v1/admin", tags=["admin"])` mounted on a FastAPI app, run by uvicorn **in the same process** as the consumer pool (so worker control is in-process). Mirror the `service_webapp` app/lifespan + standard response-envelope conventions. All routes `async def`. [Source: architecture.md#1.12.1 (management/api.py is in cdr-pipeline); service_webapp/src/main.py (app factory/lifespan)]
- [ ] **Task 2: Admin JWT guard (role = admin)** (AC: #5)
  - [ ] Reuse the auth pattern from `service_webapp/src/core/auth.py`: a `JWTValidator(jwks_url).decode(token)` (RS256 against Cognito JWKS) + a `require_role("admin")` FastAPI dependency that extracts the Bearer token, validates, and checks `payload["cognito:groups"]` for `admin` — raising `UnauthenticatedError` (401) / `ForbiddenError` (403). [Source: service_webapp/src/core/auth.py:51-90,121-167]
  - [ ] **Cross-codebase note:** `core/auth.py` lives in `service_webapp`; there is no shared package (MVP two-codebase rule). Port a minimal `JWTValidator` + `require_role` into `cdr-pipeline/src/core/auth.py`, keeping the contract identical (same JWKS, same `cognito:groups` claim, same error types). Flag the duplication in Completion Notes as a candidate for a future shared module. Add Cognito JWKS/config keys to `cdr-pipeline/src/core/config.py` (`cognito_user_pool_id`, `cognito_client_id`, `cognito_region`, `cognito_endpoint_url`) mirroring service_webapp. [Source: architecture.md#1.5.1 (no inter-service HTTP / no shared pkg); 1-8 story (cognito:groups, JWKS)]
- [ ] **Task 3: Worker control (pause/resume within 2s)** (AC: #3, #4)
  - [ ] Add a shared `WorkerController` holding an `asyncio.Event` (set = running). The Story 2.2 batch loop `await`s `controller.running.wait()` **before each `getmany` poll**; `pause()` clears the event, `resume()` sets it. Because polling cycles are sub-second, clearing the event halts new polling well within 2s. The management endpoints call `controller.pause()/resume()` on the shared instance (same process). [Source: epics.md#Story-2.5 (line 984); architecture.md#1.4.3 (FastAPI = management plane, never hot path)]
  - [ ] Document the single-process topology (consumer tasks + management API on one event loop). If the deployment splits them into separate processes, the fallback is a Valkey control flag (`control:cdr_workers`) the consumer checks each batch — note which was implemented.
- [ ] **Task 4: DLQ inspection** (AC: #1, #2)
  - [ ] `GET /api/v1/admin/dlq` — consume/peek `cdr.dlq` via a transient aiokafka consumer (own group id, `auto_offset_reset="earliest"`, no commit) and return a paginated list (query params `limit`, `offset` or a cursor) of `{cdr_id, error_reason, original_topic, failed_at, raw_payload_preview}`. The preview must be **PII-masked** (mask MSISDNs/IMEI). The metadata shape is exactly what Story 2.2's DLQ handler writes. [Source: epics.md#Story-2.2 (DLQ metadata), #Story-2.5]
  - [ ] `GET /api/v1/admin/dlq/{cdr_id}` — return the full raw payload for the matching DLQ record (still mask PII in the response per hygiene rules; "full" = full structure, masked values).
  - [ ] Responses use the standard success envelope (`{data, meta:{trace_id,...}}`); errors use the standard error envelope. [Source: architecture.md#1.11.3; service_webapp/src/core/responses.py]
- [ ] **Task 5: Wire into main + justfile** (AC: #3, #4)
  - [ ] `cdr-pipeline/src/main.py` — start the consumer pool AND the management API (uvicorn) on the same loop, sharing the `WorkerController`. Add a `just cdr-admin` (or extend `just up`) recipe / compose wiring so the management API is reachable; pick a dedicated port and document it. [Source: 1-3 story (justfile recipes)]
- [ ] **Task 6: Tests** (AC: #1, #2, #3, #4, #5)
  - [ ] Unit (httpx.AsyncClient): no/invalid token → 401; valid token without `admin` group → 403; `admin` token → 200 on all four endpoints (mock `JWTValidator.decode`). [Source: service_webapp test patterns]
  - [ ] Unit: `pause` clears the controller event and the batch loop's pre-poll `wait()` blocks; `resume` sets it and polling continues; endpoints return `{status:"paused"}` / `{status:"running"}`.
  - [ ] Unit: DLQ list pagination + PII masking (mock the dlq consumer with sample records).
  - [ ] Integration (`@pytest.mark.slow`, testcontainers Redpanda): publish to `cdr.dlq`, assert `GET /dlq` returns it with correct metadata. Rootless podman.

## Dev Notes

### Scope boundary

- **DOES:** the cdr-pipeline management FastAPI app, admin-only JWT guard (role `admin`), DLQ list + single-event inspect (PII-masked), worker pause/resume (≤2s, in-process), wiring + tests.
- **DOES NOT:** DLQ **replay** to `cdr.raw` (the epic's broader vision mentions replay; this story's ACs cover inspect only — implement only if trivially additive, else defer and note), build the consumer itself (2.2) or balance/audit logic (2.3/2.4), or any subscriber-facing endpoint.

### 🚨 Placement decision — management API lives in `cdr-pipeline`, not `service_webapp`

- Architecture §1.12.1 explicitly places `management/api.py` inside `cdr-pipeline`. Worker pause/resume must control the **cdr-pipeline consumer coroutines**, which is only clean if the API shares the consumer's process/event loop (in-process `asyncio.Event`). Putting it in `service_webapp` (a separate process) would force a Valkey-flag indirection and couldn't guarantee the 2s stop as directly. **Build it in `cdr-pipeline`.** [Source: architecture.md#1.12.1 (cdr-pipeline/src/management/api.py), #1.4.3 (FastAPI management plane, off hot path)]
- Trade-off: `cdr-pipeline` has had no FastAPI app or auth until now (it was a pure consumer). This story introduces both. Add `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `PyJWT[crypto]>=2.8` to `cdr-pipeline/pyproject.toml` runtime + tox env `deps`.

### Reuse the Story 1.8 auth contract (don't reinvent)

- `service_webapp/src/core/auth.py` already implements `JWTValidator.decode()` (RS256, `jwt.PyJWKClient` JWKS caching) and `require_role(*roles)` reading `cognito:groups`. Port the **same** logic into `cdr-pipeline/src/core/auth.py` — identical claim name, identical error types (`UnauthenticatedError`→401, `ForbiddenError`→403), identical envelope. Roles are delivered via `cognito:groups` (NOT a custom `role` claim); valid roles include `admin`. [Source: service_webapp/src/core/auth.py:51-90,121-167; 1-8 story (cognito:groups, 30-min access token); architecture.md#1.8.1-1.8.2]
- Error handling/exception handlers and `success_envelope` come from `service_webapp/src/core/{errors,responses}.py` — port the equivalents (or copy minimal versions) so the management API's responses match the platform's envelope conventions. [Source: service_webapp/src/core/errors.py:25-76, responses.py:21-23; architecture.md#1.11.3]

### Worker control mechanism (AC #3 — the 2s guarantee)

- Single source of truth = a `WorkerController` with `asyncio.Event` (running). Story 2.2's `batch_processor` loop calls `await controller.running.wait()` immediately before `getmany(...)`. `pause()` → `event.clear()` → the next loop iteration blocks before polling; in-flight batch finishes (and commits) then the loop parks. Since `getmany` cycles are sub-second, "stop polling within 2s" holds. `resume()` → `event.set()`. Endpoints return the literal `{"status":"paused"}` / `{"status":"running"}`. [Source: epics.md#Story-2.5 (lines 983-986)]
- This requires a small seam in Story 2.2's loop (the pre-poll `wait()`); if 2.2 is already merged without it, add the hook here and note the cross-story edit.

### DLQ metadata contract (must match Story 2.2)

- Story 2.2's `dlq/handler.py` writes `cdr.dlq` records with `error_reason`, `original_topic`, `failed_at`, raw payload, keyed by `cdr_id`. This API reads them back. Keep the field names identical across the two stories — if they drift, the inspect endpoint returns nulls. Reading the DLQ uses a transient non-committing consumer so inspection doesn't consume the queue. [Source: epics.md#Story-2.2 (DLQ metadata), this epic Story 2.2]

### PII hygiene (mandatory in responses)

- DLQ raw payloads contain CDR data (MSISDN, IMEI, numbers). The inspect responses MUST mask: `msisdn[-4:]`, IMEI redacted, etc. Never return or log raw PII. Use the masking helper pattern from Story 1.6 (`mask_msisdn`). [Source: architecture.md#1.11.6; 1-6 story]

### Async-only, standard envelope, versioned path

- All routes `async def`; path prefix `/api/v1/admin`; pagination via `limit`/`offset` query params; success + error envelopes per §1.11.3. Match `service_webapp/src/routers/account.py` router/DI style (`APIRouter(prefix=...)`, service pulled from `request.app.state`). [Source: service_webapp/src/routers/account.py:28-29,123-134; architecture.md#1.11.3 (ARCH-15 async)]

### Config & deps

- `cdr-pipeline/src/core/config.py` gains Cognito keys (JWKS/pool/client/region/endpoint). `settings.kafka_brokers` already present for the DLQ consumer. Add `fastapi`, `uvicorn[standard]`, `PyJWT[crypto]`, `aiokafka` to runtime + tox env deps. [Source: cdr-pipeline/src/core/config.py; 1-8 story (cognito config keys)]

### Testing standards summary

- `uv tox` `lint`/`test`; `httpx.AsyncClient` for API tests with a mocked `JWTValidator.decode` (no live Cognito); auth matrix (401/403/200) is the critical coverage. One `slow` testcontainers Redpanda integration for real DLQ read. Add new imports to tox env `deps`. [Source: service_webapp test conventions; 1-4 story; cdr-pipeline/pyproject.toml]

### Project Structure Notes

- **NEW:** `cdr-pipeline/src/management/{__init__,api}.py`, `cdr-pipeline/src/core/auth.py` (ported), `cdr-pipeline/src/core/{errors,responses}.py` (ported/minimal), a `WorkerController` (e.g. `cdr-pipeline/src/consumer/control.py`), tests under `cdr-pipeline/tests/`.
- **MODIFIES:** `cdr-pipeline/src/main.py` (run consumer + management API on one loop, share `WorkerController`), Story 2.2 `batch_processor` (pre-poll `wait()` seam), `cdr-pipeline/src/core/config.py` (Cognito keys), `cdr-pipeline/pyproject.toml` (FastAPI/uvicorn/PyJWT deps), root `justfile`/compose (expose the admin port).
- **App role / claim:** role is the `admin` value inside the `cognito:groups` claim (not a custom `role` claim). [Source: 1-8 story]

### References

- [Source: epics.md#Story-2.5 (lines 962-988)]
- [Source: architecture.md#1.12.1 (cdr-pipeline/src/management/api.py), #1.4.3 (FastAPI management plane, off hot path)]
- [Source: architecture.md#1.8.1-1.8.2 (Cognito JWT, cognito:groups, role guards), #1.11.3 (response envelopes)]
- [Source: architecture.md#1.5.1 (two-codebase MVP, no shared pkg), #1.11.6 (PII hygiene)]
- [Source: service_webapp/src/core/auth.py:51-90,121-167 (JWTValidator, require_role)]
- [Source: service_webapp/src/routers/account.py:28-29,123-134 (router/DI pattern), src/core/responses.py:21-23, src/core/errors.py:25-76]
- [Source: 1-8 story (cognito:groups, JWKS, 30-min token, admin role), 1-6 story (mask_msisdn), 1-3 story (justfile), 1-4 story (testcontainers)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
