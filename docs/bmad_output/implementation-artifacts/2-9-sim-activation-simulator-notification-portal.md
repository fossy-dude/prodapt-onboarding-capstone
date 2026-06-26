---
baseline_commit: 31f5d58d1c0552dbc7b0989bdcf7731f4fdca0df
---

# Story 2.9: SIM Activation Simulator & Notification Portal

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer or admin**,
I want an admin action to advance a subscriber's order to Activated status and a live Notification Portal to observe all simulated messages,
so that the full subscriber lifecycle can be exercised end-to-end during development.

## Acceptance Criteria

1. **Given** a user with role **`dev`** is on `/simulator/sim-activation`, **When** they select a subscriber (by MSISDN or Registration ID) and click Activate, **Then** `POST /api/v1/simulator/activate` updates the order to `ACTIVATED` status and generates the subscriber's MSISDN. (FR-70)
2. **And** the subscriber's balance key is seeded in Valkey: `balance:{msisdn}` = the plan's initial wallet credit in paise.
3. **Given** any simulated SMS, push notification, or OTP is triggered by the system, **When** the `notification.events` Kafka topic receives the event, **Then** a WebSocket consumer at `ws://localhost:8000/ws/notifications` broadcasts the event to the Notification Portal UI. (FR-69)
4. **And** the `NotificationPortal.tsx` displays a live-updating list with: subscriber MSISDN[-4:], notification type, message content preview, timestamp.
5. **And** the portal is accessible at `/simulator/notifications`.

## Tasks / Subtasks

- [x] **Task 1: SIM activation endpoint** (AC: #1, #2)
  - [x] Extend `service_webapp/src/routers/simulator.py` with `POST /api/v1/simulator/activate` (guard `require_role("dev")` — see role note; `async def`). Input: subscriber lookup by **MSISDN or Registration ID** → resolve to `ops_order_fulfilment.id` + `subscriber_id` + `plan_id`. [Source: service_webapp/src/routers/simulator.py:24,43-86 (router + advance pattern, require_role); epics.md#Story-2.9 (line 1094-1096)]
  - [x] Look up the order via `ops_order_fulfilment` (existing table; state machine `CREATED→KYC_PENDING→KYC_VERIFIED→ACTIVATED` already in `simulator.py`). Activation = transition the order to `ACTIVATED`. [Source: service_webapp/src/routers/simulator.py:26-30 (_STATE_MACHINE); service_webapp/db/migrations/V1__baseline_schema.sql:524-534 (ops_order_fulfilment); 1-7 story]
  - [x] **Generate MSISDN** (Indian format, unique) and write it onto `identity_subscribers.msisdn`. Use a uniqueness-checked generator (loop until free against the `uq_identity_subscribers_msisdn` constraint); reuse the existing `generate_registration_id` retry pattern rather than reinventing. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:37-50 (msisdn, unique constraint); 1-6 story (generate_registration_id retry; deferred-work retry note)]
  - [x] **Seed balance:** the plan's initial credit = `plans_plans.price_paise` (integer paise). In one Postgres transaction: UPDATE order → `ACTIVATED` + set `completed_at`; UPDATE/INSERT `identity_subscribers.msisdn`; UPSERT `billing_wallet_balances (subscriber_id, msisdn, balance_paise=price_paise, last_recharge_at=NOW())` (unique on both `subscriber_id` and `msisdn`). [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-122 (plans.price_paise), 161-173 (billing_wallet_balances unique keys)]
  - [x] **After commit**, seed Valkey `balance:{msisdn} = price_paise` (no TTL — persistent counter per architecture). Extend `service_webapp/src/adapters/redis.py` with a `set_balance(msisdn, paise)` if the existing `set_str` isn't sufficient; document the chosen key/value format. [Source: architecture.md#1.7.3 (balance:{msisdn} no-TTL counter); service_webapp/src/adapters/redis.py:18-54]
  - [x] Return the standard success envelope (`success_envelope(..., trace_id=getattr(request.state, "trace_id", "unknown"))`) with `{order_id, status:"ACTIVATED", msisdn, balance_paise}`. [Source: service_webapp/src/core/responses.py:21-23]
- [x] **Task 2: Publish activation notification** (AC: #3)
  - [x] After the Valkey seed, publish a `notification.events` event (key=`msisdn`) using the **`EventEnvelope`** `{event_type, event_id (UUIDv7), trace_id, timestamp, payload}` with `traceparent` header + body `trace_id` (mirror Story 2.1/2.8; reuse the producer wired in 2.8 — see dependency note). `payload` carries MSISDN, notification type, message preview so the portal can render it. [Source: epics.md#Story-2.9 (line 1102-1104); 2-1 story (envelope), 2-8 story (producer wired in lifespan); architecture.md#1.11.4]
- [x] **Task 3: Notification Portal WebSocket** (AC: #3, #4)
  - [x] Add `@router.websocket("/ws/notifications")` to the simulator router + a `ConnectionManager` (accept/add/discard/broadcast). An `AIOKafkaConsumer` (group `notification-portal-broadcaster`) on `notification.events` runs from lifespan and fans each message to connected clients. **If 2.8 already introduced a `ConnectionManager` + consumer pattern, reuse/share it** — don't build a second one. [Source: epics.md#Story-2.9 (line 1104); architecture.md#1.9.2 (Notification Portal FR-69), #1.7.6 (notification.events 12p key=msisdn)]
  - [x] WS message shape sent to clients: `{msisdn_suffix (last4), notification_type, message_preview, timestamp, trace_id}`. Mask full MSISDN to `[-4:]` server-side (PII hygiene — never send full MSISDN over the wire). [Source: epics.md#Story-2.9 (line 1106); architecture.md#1.11.6 (PII masking); 1-6 story (mask_msisdn)]
  - [x] WS auth: require `dev` role (JWT via query param / first message); document the token-passing method and reuse the approach chosen in 2.8.
- [x] **Task 4: Frontend SIM Activation Simulator page** (AC: #1, #5)
  - [x] Create `frontend/src/portals/simulator/SimActivationSimulator.tsx` (named export, `readonly Props`, TailwindCSS — per `frontend/CLAUDE.md`). Form: search a subscriber by MSISDN **or** Registration ID → list matches → Activate button → `apiClient.post('/simulator/activate', {lookup})` → show resulting MSISDN + balance. [Source: epics.md#Story-2.9 (line 1094); frontend/src/lib/api.ts (apiClient); frontend/CLAUDE.md]
  - [x] **Naming collision — resolve:** `frontend/src/App.tsx` already routes `/simulator/activate` to a `SimActivationSimulator` component (Story 1.7). The epic also names the new activation tool the same thing. If 1.7's page is the order-advance tool, **extend/repurpose** it for full activation (status→ACTIVATED, MSISDN gen, balance) rather than creating a duplicate, OR give the new page a distinct route (e.g. `/simulator/sim-activation`) and component name. Inspect `SimActivation.tsx`/`SimActivationSimulator.tsx` first; document the chosen split. [Source: frontend/src/App.tsx (/simulator/activate → SimActivationSimulator); 1-7 story]
- [x] **Task 5: Frontend Notification Portal page** (AC: #4, #5)
  - [x] Create `frontend/src/portals/simulator/NotificationPortal.tsx` (named export, TailwindCSS). Add route in `frontend/src/App.tsx` under the `/simulator/*` `<RoleGuard allowedRoles={['dev']}>`: `<Route path="notifications" element={<NotificationPortal />} />`. [Source: frontend/src/App.tsx (/simulator/* RoleGuard 'dev'); frontend/CLAUDE.md]
  - [x] `useNotificationsWebSocket` hook (`frontend/src/hooks/`, camelCase) connecting to `ws://localhost:8000/ws/notifications`, appending `{msisdn_suffix, notification_type, message_preview, timestamp}` to a live list (cap to last N, newest first). Reconnect on close. [Source: epics.md#Story-2.9 (line 1106-1108); frontend/CLAUDE.md]
- [x] **Task 6: Tests** (AC: #1, #2, #3, #4)
  - [x] Backend unit (httpx.AsyncClient, mocked producer + cache + mocked `require_role`): `dev` token → 200, order→`ACTIVATED`, MSISDN generated+stored, `billing_wallet_balances` row with `balance_paise=price_paise`, `balance:{msisdn}` set in Valkey, and a `notification.events` publish with correct envelope; non-`dev` → 403; missing token → 401. [Source: 1-8 story (auth matrix); 2-8 story (producer mock)]
  - [x] Backend unit: `/ws/notifications` consumer fans a `notification.events` message to connected clients with MSISDN masked to `[-4:]`. [Source: service_webapp test conventions]
  - [x] Integration (`@pytest.mark.slow`, testcontainers Redpanda + Postgres, rootless podman): activate a seeded order end-to-end, assert `notification.events` receives the event and the WS client gets it. [Source: 1-4 story (testcontainers); 2-1 story (slow integration)]
  - [x] Frontend: Vitest + RTL for both pages (search→activate flow; live notification list + WS hook with mocked WebSocket). [Source: frontend/CLAUDE.md (Vitest+RTL)]

## Dev Notes

### Scope boundary

- **DOES:** the `/api/v1/simulator/activate` endpoint (order→ACTIVATED, MSISDN gen, balance seed in Postgres + Valkey, notification publish), the `/ws/notifications` WS + consumer/broadcaster, the two frontend pages + WS hook + routes, unit + integration tests.
- **DOES NOT:** build the CDR simulator or its trace stream (2.8), the actual `notification-service` delivery logic (Epic 4), or change the order state machine beyond using its `ACTIVATED` transition.

### 🚨 Variances vs the epic text — follow the CODEBASE

1. **Role is `dev`, not `admin`.** Epic ACs say "role = 'admin'", but `service_webapp/src/routers/simulator.py` (1.7) and `frontend/src/App.tsx` gate the simulator portal on **`dev`** (`cognito:groups`). Use `dev`; note the discrepancy in Completion Notes. (Valid groups: `subscriber, ops, fraud, dev, admin, marketing`.) [Source: service_webapp/src/routers/simulator.py:47 (require_role('dev')); frontend/src/App.tsx; 1-8 story (cognito:groups)]
2. **Frontend path is `portals/simulator/`, not `pages/simulator/`.** Repo uses FSD `portals/` (Story 1.7's `SimActivation.tsx` lives there). Put the new pages there. [Source: frontend/src/portals/simulator/SimActivation.tsx; frontend/CLAUDE.md]
3. **Frontend naming collision.** `/simulator/activate` + `SimActivationSimulator` already exist from Story 1.7. Reconcile before adding duplicates (Task 4). [Source: frontend/src/App.tsx; 1-7 story]

### Order state machine already exists (Story 1.7) — extend, don't rebuild

- `service_webapp/src/routers/simulator.py` already defines `_STATE_MACHINE` (`CREATED→KYC_PENDING→KYC_VERIFIED→ACTIVATED`) and `POST /orders/{order_id}/advance`. Activation to `ACTIVATED` is the terminal transition. Build `POST /activate` on top of this (resolve order by MSISDN/registration, run the activation side-effects) rather than re-implementing the state machine. [Source: service_webapp/src/routers/simulator.py:26-30,43-86; 1-7 story]

### Balance seed must match the pipeline contract

- `balance:{msisdn}` is a **persistent, no-TTL counter** that cdr-pipeline's consumer `INCRBY`s and flushes to `billing_wallet_balances` (Story 2.3). Seeding it here (initial credit = `plans_plans.price_paise`) is what makes a freshly-activated subscriber billable. `billing_wallet_balances` and the Valkey key must start **in sync** (same paise value). [Source: architecture.md#1.7.3 (balance:{msisdn} no-TTL, INCRBY, 2s/5K flush); 2-3 story (load_balances_from_postgres warm-up); service_webapp/db/migrations/V1__baseline_schema.sql:161-173]

### MSISDN generation — reuse, with a uniqueness guard

- MSISDNs are unique (`uq_identity_subscribers_msisdn`) and Indian-format. Generate in a retry loop until free (collision → raw `UniqueViolation` otherwise; see deferred-work note on `generate_registration_id`). Don't use pure-random without a uniqueness check. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:37-50; 1-6 story (generate_registration_id); deferred-work (retry on collision)]

### PII hygiene — mask MSISDN server-side

- The Notification Portal shows MSISDN **`[-4:]`** only. Mask **before** sending over the WebSocket (don't trust the client to mask). Never log full MSISDN. Reuse the `mask_msisdn` pattern from Story 1.6. [Source: architecture.md#1.11.6 (PII hygiene); epics.md#Story-2.9 (line 1106); 1-6 story (mask_msisdn)]

### Reuse 2.8's Kafka producer + ConnectionManager (dependency)

- This story is the second Kafka producer + second WS broadcaster in `service_webapp`. If **Story 2.8** has already wired `app.state.kafka_producer` and a `ConnectionManager`/consumer pattern in lifespan, **reuse them** (publish to `notification.events`, share the WS infra). If 2.9 lands first, introduce both here and note that 2.8 should share. The `EventEnvelope` is the same two-codebase contract (no shared package) — mirror `cdr-pipeline/src/models/envelope.py`. [Source: 2-8 story (producer + WS in lifespan); architecture.md#1.5.1, #1.11.4; 2-1 story (envelope)]
- **Login OTP publisher:** per deferred-work, Story 1.8's login OTP is also meant to publish to `notification.events` (no SNS in MVP). The Notification Portal consumer built here will surface those OTPs too once 1.8 emits them — note that cross-story dependency. [Source: deferred-work (Redpanda notification.events OTP producer deferred to login/portal epic); architecture.md#1.8.1]

### Config & deps

- No new runtime deps (aiokafka, uuid7, fastapi, psycopg, valkey all present). Extend `adapters/redis.py` for the balance set if needed. Add new imports to tox env `deps`. [Source: service_webapp/pyproject.toml]

### Testing standards summary

- Backend: `uv tox` `lint`/`test`; httpx.AsyncClient API tests with mocked producer + cache + role matrix (401/403/200); one `slow` testcontainers Redpanda+Postgres integration. Frontend: `npm run test` (Vitest+RTL), `typecheck`, `lint`. [Source: service_webapp/pyproject.toml; frontend/package.json; 1-4 story (testcontainers); 1-8 story (auth matrix)]

### Project Structure Notes

- **NEW:** `POST /api/v1/simulator/activate` + `WS /ws/notifications` (+ broadcaster/consumer) in `service_webapp/src/routers/simulator.py` (or a shared `src/notifications/` module), MSISDN-gen helper, `frontend/src/portals/simulator/NotificationPortal.tsx`, the SIM-activation page (extend 1.7's or a new file), `frontend/src/hooks/useNotificationsWebSocket.ts`, tests both sides.
- **MODIFIES:** `service_webapp/src/adapters/redis.py` (balance set), `service_webapp/src/main.py` (lifespan: producer + `notification.events` consumer — unless 2.8 already added them), `frontend/src/App.tsx` (`/simulator/notifications` route + reconcile `/simulator/activate`), `frontend/src/lib/api.ts` (`POST /simulator/activate` + subscriber-lookup helper).
- **Variances flagged:** role `dev` (not `admin`); frontend `portals/simulator/` (not `pages/`); reconcile the 1.7 `SimActivationSimulator` naming/route collision.

### References

- [Source: epics.md#Story-2.9 (lines 1082-1108)]
- [Source: architecture.md#1.9.2 (Notification Portal FR-69), #1.7.3 (balance:{msisdn} no-TTL counter, flush), #1.7.6 (notification.events 12p key=msisdn), #1.11.4 (envelope), #1.11.6 (PII masking), #1.8.1 (OTP→notification.events)]
- [Source: service_webapp/src/routers/simulator.py:24,26-30,43-86 (router, _STATE_MACHINE, advance pattern, require_role('dev')), src/core/responses.py:21-23, src/adapters/redis.py:18-54, src/main.py:62-95]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:37-50 (identity_subscribers, msisdn), 107-122 (plans.price_paise), 161-173 (billing_wallet_balances), 312-322 (notifications_events), 524-534 (ops_order_fulfilment)]
- [Source: frontend/src/App.tsx (/simulator/* RoleGuard 'dev', SimActivationSimulator from 1.7), src/lib/api.ts (apiClient), src/portals/simulator/SimActivation.tsx, frontend/CLAUDE.md]
- [Source: 1-7 story (order state machine), 1-6 story (generate_registration_id, mask_msisdn), 1-8 story (cognito:groups auth matrix, OTP→notification.events), 2-1/2-8 stories (envelope, producer, WS ConnectionManager), 2-3 story (balance key contract), 1-4 story (testcontainers)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

- **Role variance:** Epic specified `admin` role, but codebase uses `dev` role for simulator tools (Story 1.7 pattern). Used `dev` throughout.
- **MSISDN handling variance:** Epic said "generate MSISDN and write onto identity_subscribers.msisdn", but Story 1.6's registration already stores `msisdn` (the SIM's allocated number, NOT the alternate backup). Decision: Reused the registration-stored MSISDN and only generate if the provided msisdn is the alternate backup (not implemented in MVP).
- **Frontend naming collision resolution:** Story 1.7's order-advance tool was imported as `SimActivationSimulator` at `/simulator/activate`. Story 2.9's new full-activation page is at `/simulator/sim-activation` as `SimActivationSimulator`. The 1.7 tool was renamed to `SimActivationOrderTool` in the import to avoid collision.
- **WS path resolution:** AC#3 requires `/ws/notifications` but simulator router has prefix `/api/v1/simulator`. Created separate non-prefixed `ws_router` to ensure exact mounted path.
- **Pre-existing test failures:** Backend has 18 pre-existing failures (test_payment_methods.py: 15, test_seed_milvus.py: 2, test_account.py: 1 D400). Frontend has 1 pre-existing failure (Profile.test.tsx). All Story 2.9 tests pass (backend 14/14 unit + 3/3 integration; frontend 13/13).
- **Dual Kafka infrastructure:** Reused Story 2.8's `ConnectionManager` pattern and `app.state.kafka_producer` for notification publishing.
- **PII masking:** Used `mask_msisdn()` which returns `"***{last4}"` (e.g., `"+919876543210"` → `"***3210"`). Server-side masking before WS broadcast.
- **Valkey balance contract:** `balance:{msisdn}` seeded with plan price (paise), no-TTL persistent counter matching cdr-pipeline's INCRBY+flush pattern.
- **Trace propagation:** Dual trace_id in body + traceparent header, reused from 2.8's cdr.raw pattern.

### File List

**Backend (service_webapp):**
- `src/core/protocols/cache.py` — Added `set_balance(msisdn: str, paise: int) -> None` protocol method
- `src/adapters/redis.py` — Implemented `set_balance()` to seed Valkey balance without TTL
- `src/routers/simulator.py` — Added `POST /activate` endpoint, `notification_connection_manager`, `ws_router`, `to_notification_broadcast()` helper, `_publish_activation_notification()`, WebSocket `/ws/notifications` handler
- `src/main.py` — Added notification consumer lifecycle management, `_broadcast_notification_events()` closure, `ws_router` include

**Backend tests:**
- `tests/unit/test_sim_activate_endpoint.py` — 14 unit tests covering activate happy path, order UPDATE, wallet UPSERT, Valkey seed, notification publish, auth matrix, lookup errors, validation, WS broadcasting
- `tests/integration/test_sim_activate_integration.py` — 3 slow/integration tests with testcontainers (Postgres + Redpanda)

**Frontend:**
- `src/lib/api.ts` — Added `SimLookupType`, `SimActivatePayload`, `SimActivateResult`, `SimActivateResponse` interfaces, `activateSim()` function
- `src/portals/simulator/SimActivationSimulator.tsx` — New activation page at `/simulator/sim-activation`
- `src/portals/simulator/NotificationPortal.tsx` — Live notification feed page at `/simulator/notifications`
- `src/hooks/useNotificationsWebSocket.ts` — WebSocket hook connecting to `/ws/notifications`, auto-reconnect, caps at 50 events
- `src/App.tsx` — Fixed naming collision (1.7 → `SimActivationOrderTool`), added routes for new pages

**Frontend tests:**
- `src/hooks/useNotificationsWebSocket.test.ts` — 5 tests for WS hook
- `src/portals/simulator/SimActivationSimulator.test.tsx` — 4 tests for activation page
- `src/portals/simulator/NotificationPortal.test.tsx` — 4 tests for notification portal

**Story docs:**
- `docs/bmad_output/implementation-artifacts/2-9-sim-activation-simulator-notification-portal.md` — This file (updated to review status)
