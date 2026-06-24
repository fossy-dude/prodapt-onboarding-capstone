---
baseline_commit: b1dda60
---

# Story 4.4: USSD Session Handler & Menu Router

Status: review

## Story

As a **subscriber**,
I want to use USSD to access a text menu for balance, plan info, recharge, and notification preferences,
so that I can self-serve from any basic phone without internet access.

## Acceptance Criteria

1. **Given** the telecom operator sends a USSD callback to `POST /api/v1/ussd/callback`, **When** the request body contains `{msisdn, session_id, button_pressed, ussd_string}`, **Then** the handler retrieves or initialises session state from Valkey HASH `session:{session_id}` with 30-minute TTL (FR-37, ARCH-5). [Source: epics.md:1436–1443]
2. **And** the response body is a structured text menu string per USSD protocol format (Content-Type: text/plain, HTTP 200). [Source: epics.md:1441–1443]
3. **Given** a subscriber dials the USSD code (session start, `button_pressed` is empty), **When** the root menu is displayed, **Then** the response is: `"Welcome\n1. Balance\n2. My Plan\n3. Recharge\n4. Notifications\n0. Exit"`. [Source: epics.md:1444–1449]
4. **Given** a subscriber selects option 1 (Balance), **When** the handler processes `button_pressed = "1"`, **Then** it reads `balance:{msisdn}` from Valkey and responds: `"Your balance is ₹{X.XX}\n0. Back"` (FR-38). [Source: epics.md:1450–1455]
5. **Given** a subscriber selects option 2 (My Plan), **When** the handler processes `button_pressed = "2"`, **Then** it responds with active plan name, validity expiry, and remaining data/voice/SMS (FR-39). [Source: epics.md:1456–1461]
6. **Given** a subscriber selects option 3 (Recharge) and then a plan, **When** the handler processes the selection, **Then** it displays a confirmation screen with the plan price and "Press 1 to confirm" (FR-40). [Source: epics.md:1462–1467]
7. **And** on confirmation, `POST /api/v1/subscriber/recharge` is called internally with a default saved payment method; result is shown as USSD text. [Source: epics.md:1468–1469]
8. **Given** a subscriber selects option 4 (Notifications), **When** the handler processes the selection, **Then** it shows current opt-in status per type and allows toggling via button press (FR-41). [Source: epics.md:1470–1475]
9. **Given** a subscriber presses 0 at any menu level, **When** the handler processes `button_pressed = "0"`, **Then** if at root the session is terminated with `"Thank you. Goodbye."` and the session key is deleted from Valkey; otherwise the subscriber is returned to the root menu. [Source: epics.md:1444–1449, 1475]
10. **Given** an unknown MSISDN is received, **When** the handler queries identity_subscribers, **Then** it returns USSD text `"Unknown subscriber.\n0. Exit"` (no crash). [Source: architecture.md USSD constraints]

## Tasks / Subtasks

- [x] **Task 1: Extend CacheProtocol + ValkeyAdapter for HASH operations** (AC: #1)
  - [x] Add `async def hset(self, key: str, mapping: dict[str, str], *, ex: int | None = None) -> None` to `CacheProtocol` (`core/protocols/cache.py`). [Source: adapters/redis.py; core/protocols/cache.py]
  - [x] Add `async def hgetall(self, key: str) -> dict[str, str]` to `CacheProtocol`. [Source: core/protocols/cache.py]
  - [x] Implement `hset` and `hgetall` on `ValkeyAdapter` (`adapters/redis.py`). Use `await self._client.hset(key, mapping=mapping)` and `await self._client.expire(key, ex)` if `ex` is set. [Source: adapters/redis.py:18–54]

- [x] **Task 2: Pydantic models** (AC: #1–#2)
  - [x] Create `service_webapp/src/models/ussd.py` (NEW): `UssdCallbackRequest(BaseModel)` with fields `msisdn: str`, `session_id: str`, `button_pressed: str = ""`, `ussd_string: str = ""`. Add `UssdMenuState` as `Literal["root", "balance", "plan", "recharge_select", "recharge_confirm", "notifications"]`. [Source: epics.md:1438; architecture.md ARCH-5]

- [x] **Task 3: DB query helpers** (AC: #5–#7)
  - [x] Create `service_webapp/src/db/plans/` directory with `__init__.py` and `queries.py`. Add:
    - `get_active_subscription(db, subscriber_id: str) -> dict | None` — raw SQL joining `plans_subscriptions ps JOIN plans_plans p ON ps.plan_id = p.id WHERE ps.subscriber_id = %s AND ps.status = 'active' LIMIT 1`. Returns plan name, expiry, data_limit_mb, voice_minutes, sms_count. [Source: architecture.md:1112–1114; V1 migration plans tables]
    - `get_available_plans(db, limit: int = 5) -> list[dict]` — `SELECT id, name, price_paise, data_limit_mb, voice_minutes, sms_count FROM plans_plans WHERE is_active = TRUE LIMIT %s`. [Source: V1 migration plans tables]
  - [x] Add `get_subscriber_by_msisdn(db, msisdn: str) -> dict | None` to `service_webapp/src/db/identity/queries.py` (NEW). Raw SQL on `identity_subscribers`. [Source: V1 migration identity tables]

- [x] **Task 4: USSD router** (AC: #1–#10)
  - [x] Create `service_webapp/src/routers/ussd.py` (NEW). `APIRouter(prefix="/api/v1/ussd", tags=["ussd"])`. No JWT auth dependency (USSD callbacks come from telecom operator, not subscriber browser). [Source: epics.md:1436; architecture.md USSD inbound-only]
  - [x] `POST /callback` accepts `UssdCallbackRequest`, returns `Response(content=text, media_type="text/plain")`. [Source: epics.md:1436–1443]
  - [x] Session load: `hgetall(f"session:{req.session_id}")` → empty dict means new session → default to root state. Session dict: `{menu_state, subscriber_id, last_selected_plan_id}`. [Source: architecture.md ARCH-5; epics.md:1440]
  - [x] Dispatch on `(session.menu_state, req.button_pressed)`: all 11 branches implemented (root/balance/plan/recharge_select/recharge_confirm/notifications + exit + unknown MSISDN). [Source: epics.md:1444–1475]
  - [x] After every response: `await cache.hset(f"session:{req.session_id}", updated_state, ex=1800)` to reset 30-minute TTL. [Source: epics.md:1440; ARCH-5]
  - [x] Balance display: fall back to `billing_wallet_balances.balance_paise` on Valkey cold-cache miss. [Source: architecture.md:1.7.3 balance read path]

- [x] **Task 5: Wire router into main.py** (AC: #1)
  - [x] In `service_webapp/src/main.py`: import `ussd_router` from `routers.ussd`; `app.include_router(ussd_router)`. [Source: main.py:236–238]

- [x] **Task 6: Tests** (AC: #1–#10)
  - [x] Unit (httpx.AsyncClient, mocked cache + DB): root menu text exact match; balance option reads Valkey key; plan option returns name+expiry+remaining; exit at root deletes session; exit at sub-menu returns root menu; unknown MSISDN returns error text. 15 unit tests passing. [Source: 1-4 story test patterns]
  - [x] Unit: session HASH saved to Valkey with TTL=1800 on every request.
  - [x] Unit: recharge_confirm "1" → recharge command called with correct subscriber_id + plan_id + payment_method_id.
  - [x] Integration (slow, `@pytest.mark.slow`): testcontainers Postgres + Valkey; full session flow: root → balance → back → recharge_select → confirm → result. [Source: 1-4 story; architecture.md conftest testcontainers]

## Dev Notes

### No JWT on USSD endpoint

USSD callbacks originate from the telecom operator's network (not the subscriber's HTTP client), so they carry no Authorization header. Do NOT add `Depends(require_role(...))` to the `/callback` route. MSISDN identity comes from the request body and is validated against `identity_subscribers`. [Source: architecture.md — "USSD is inbound callback only — system never initiates USSD sessions"]

### Session state is a Valkey HASH, not a JSON string

Use `hset(key, mapping)` / `hgetall(key)` (HASH operations), not `set_str` / `get_str`. The HASH gives O(1) field-level reads. All values are strings (Valkey HASH values are strings); parse ints/floats as needed. [Source: architecture.md ARCH-5 — `session:{session_id}` HASH 30m TTL]

### Plan list position vs ID mapping

When entering `recharge_select`, store the ordered plan IDs in the session (e.g. `plan_ids: "uuid1,uuid2,uuid3"`) so when `button_pressed = "2"` arrives in `recharge_confirm`, you can look up the correct plan by position without a second DB query. [Source: epics.md:1462–1468]

### Recharge internal call pattern

Do NOT make an HTTP request to `POST /api/v1/subscriber/recharge` from within the USSD handler (no self-HTTP). Instead, call the same DB commands directly: insert a row into `recharge_orders`, call `cache.incr_by(f"balance:{msisdn}", recharge_paise)`, and upsert `billing_wallet_balances`. Story 3.5 contains the canonical SQL for this. [Source: epics.md:1468; 3-5 story recharge SQL]

### Primary payment method

For USSD recharge, use the subscriber's first `recharge_payment_methods` row (ordered by `created_at ASC`). If none exists, return `"No saved payment method.\n0. Back"`. [Source: epics.md:1468 — "default saved payment method"]

### Data/voice/SMS remaining calculation

For the "My Plan" menu, compute remaining from `plans_subscriptions + plans_plans` allowances minus CDR usage. Reuse the same SQL as `GET /usage` in `balance.py` (Story 3.2 Task 2). If quota is NULL/0, display "Unlimited". [Source: epics.md:1460; 3-2 story usage query]

### Response Content-Type

FastAPI's default is `application/json`. The USSD /callback endpoint MUST return `text/plain`. Use `return Response(content=text, media_type="text/plain")` directly — do NOT wrap in the `success_envelope()` helper. [Source: epics.md:1441–1443]

### Notification preferences dependency

The `notifications_preferences` table and `db/notifications/queries.py` are created in Story 4.2. If developing 4.4 before 4.2 is merged, stub the preference query to return all `is_enabled=True`. [Source: story 4.2; V1 migration notifications_preferences]

### Valkey maxmemory — USSD session sizing

Architecture sets `maxmemory 512mb` with `noeviction`. USSD session keys are small (~200 bytes each) with 30m TTL; at peak 10K concurrent sessions ≈ 2MB. No concern for MVP. [Source: architecture.md §1.12.3]

## Dev Agent Record

### Completion Notes

All 6 tasks implemented and verified. 15 unit tests pass; 0 regressions introduced (pre-existing 27 lint/test failures unchanged). Integration test authored for slow/testcontainers run.

Key implementation decisions:
- Session HASH stores `menu_state`, `subscriber_id`, `plan_ids` (comma-sep UUIDs), `selected_plan_id`
- `_dispatch()` extracted as a pure async function for testability; `ussd_callback` handles cache save/delete
- Recharge uses `create_recharge_order` + `complete_recharge_transaction` from existing `db/recharge/commands.py` directly (no self-HTTP per dev note)
- Balance Valkey miss falls back to `billing_wallet_balances.balance_paise`
- Notification toggle uses existing `upsert_preference` + `get_preferences` from `db/notifications/`
- `UssdCallbackRequest` import marked `# noqa: TC001` — FastAPI requires runtime access for body deserialization

## File List

- `service_webapp/src/core/protocols/cache.py` — added `hset`, `hgetall` to CacheProtocol
- `service_webapp/src/adapters/redis.py` — implemented `hset`, `hgetall` on ValkeyAdapter
- `service_webapp/src/models/ussd.py` — NEW: UssdCallbackRequest, UssdMenuState
- `service_webapp/src/db/plans/__init__.py` — NEW
- `service_webapp/src/db/plans/queries.py` — NEW: get_active_subscription, get_available_plans
- `service_webapp/src/db/identity/__init__.py` — NEW
- `service_webapp/src/db/identity/queries.py` — NEW: get_subscriber_by_msisdn
- `service_webapp/src/routers/ussd.py` — NEW: USSD session handler and menu router
- `service_webapp/src/main.py` — wired ussd_router
- `service_webapp/tests/unit/test_ussd_router.py` — NEW: 15 unit tests
- `service_webapp/tests/integration/test_ussd_integration.py` — NEW: full session flow integration test

## Change Log

- 2026-06-24: Story 4.4 USSD Session Handler & Menu Router implemented. Added HASH operations to CacheProtocol/ValkeyAdapter, created USSD router with full 11-branch dispatch state machine, DB helpers for plans/identity domains, 15 unit tests + 1 integration test.
