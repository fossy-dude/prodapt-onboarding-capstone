---
baseline_commit: b1dda60
---

# Story 4.4: USSD Session Handler & Menu Router

Status: ready-for-dev

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

- [ ] **Task 1: Extend CacheProtocol + ValkeyAdapter for HASH operations** (AC: #1)
  - [ ] Add `async def hset(self, key: str, mapping: dict[str, str], *, ex: int | None = None) -> None` to `CacheProtocol` (`core/protocols/cache.py`). [Source: adapters/redis.py; core/protocols/cache.py]
  - [ ] Add `async def hgetall(self, key: str) -> dict[str, str]` to `CacheProtocol`. [Source: core/protocols/cache.py]
  - [ ] Implement `hset` and `hgetall` on `ValkeyAdapter` (`adapters/redis.py`). Use `await self._client.hset(key, mapping=mapping)` and `await self._client.expire(key, ex)` if `ex` is set. [Source: adapters/redis.py:18–54]

- [ ] **Task 2: Pydantic models** (AC: #1–#2)
  - [ ] Create `service_webapp/src/models/ussd.py` (NEW): `UssdCallbackRequest(BaseModel)` with fields `msisdn: str`, `session_id: str`, `button_pressed: str = ""`, `ussd_string: str = ""`. Add `UssdMenuState` as `Literal["root", "balance", "plan", "recharge_select", "recharge_confirm", "notifications"]`. [Source: epics.md:1438; architecture.md ARCH-5]

- [ ] **Task 3: DB query helpers** (AC: #5–#7)
  - [ ] Create `service_webapp/src/db/plans/` directory with `__init__.py` and `queries.py`. Add:
    - `get_active_subscription(db, subscriber_id: str) -> dict | None` — raw SQL joining `plans_subscriptions ps JOIN plans_plans p ON ps.plan_id = p.id WHERE ps.subscriber_id = %s AND ps.status = 'active' LIMIT 1`. Returns plan name, expiry, data_limit_mb, voice_minutes, sms_count. [Source: architecture.md:1112–1114; V1 migration plans tables]
    - `get_available_plans(db, limit: int = 5) -> list[dict]` — `SELECT id, name, price_paise, data_limit_mb, voice_minutes, sms_count FROM plans_plans WHERE is_active = TRUE LIMIT %s`. [Source: V1 migration plans tables]
  - [ ] Add `get_subscriber_by_msisdn(db, msisdn: str) -> dict | None` to `service_webapp/src/db/identity/queries.py` (or create `db/identity/queries.py` NEW) if not already present. Raw SQL on `identity_subscribers`. [Source: V1 migration identity tables]

- [ ] **Task 4: USSD router** (AC: #1–#10)
  - [ ] Create `service_webapp/src/routers/ussd.py` (NEW). `APIRouter(prefix="/api/v1/ussd", tags=["ussd"])`. No JWT auth dependency (USSD callbacks come from telecom operator, not subscriber browser). [Source: epics.md:1436; architecture.md USSD inbound-only]
  - [ ] `POST /callback` accepts `UssdCallbackRequest`, returns `Response(content=text, media_type="text/plain")`. [Source: epics.md:1436–1443]
  - [ ] Session load: `hgetall(f"session:{req.session_id}")` → empty dict means new session → default to root state. Session dict: `{menu_state, subscriber_id, last_selected_plan_id}`. [Source: architecture.md ARCH-5; epics.md:1440]
  - [ ] Dispatch on `(session.menu_state, req.button_pressed)`:
    - Root + empty/any → display root menu
    - Root + "1" → read `balance:{msisdn}` via `cache.get_str()` → format as ₹X.XX (paise ÷ 100, 2dp); save state=balance; return balance text
    - Root + "2" → query `get_active_subscription`; save state=plan; return plan text
    - Root + "3" → query `get_available_plans(limit=5)`; save state=recharge_select, store plan list in session; return numbered plan list
    - Root + "4" → query notifications_preferences for subscriber; save state=notifications; return toggle list
    - Root + "0" → delete session key; return "Thank you. Goodbye."
    - balance|plan|notifications + "0" → restore root state; return root menu
    - recharge_select + "1"–"5" → look up plan by position; save state=recharge_confirm + selected_plan_id; return confirm screen
    - recharge_confirm + "1" → get primary payment method from `recharge_payment_methods`; call recharge DB command directly (insert recharge_orders row, call Valkey INCRBY, update billing_wallet_balances); return "Recharge successful.\n0. Back" or "Recharge failed.\n0. Back"
    - recharge_confirm + "0" → restore root; return root menu
    - notifications + "1"–"4" → toggle `is_enabled` for the corresponding type (LOW_BALANCE / BALANCE_DEPLETED / PLAN_EXPIRY_REMINDER / DATA_NUDGE) in notifications_preferences; return updated notifications menu
    - Unknown msisdn → return "Unknown subscriber.\n0. Exit"
  - [ ] After every response: `await cache.hset(f"session:{req.session_id}", updated_state, ex=1800)` to reset 30-minute TTL. [Source: epics.md:1440; ARCH-5]
  - [ ] Balance display: `paise = int(val); inr = paise / 100; f"Your balance is ₹{inr:.2f}\n0. Back"`. Handle Valkey miss (cold restart) by falling back to `billing_wallet_balances.balance_paise`. [Source: architecture.md:1.7.3 balance read path]

- [ ] **Task 5: Wire router into main.py** (AC: #1)
  - [ ] In `service_webapp/src/main.py`: import `ussd_router` from `routers.ussd`; `app.include_router(ussd_router)`. [Source: main.py:236–238]

- [ ] **Task 6: Tests** (AC: #1–#10)
  - [ ] Unit (httpx.AsyncClient, mocked cache + DB): root menu text exact match; balance option reads Valkey key; plan option returns name+expiry+remaining; exit at root deletes session; exit at sub-menu returns root menu; unknown MSISDN returns error text. [Source: 1-4 story test patterns]
  - [ ] Unit: session HASH saved to Valkey with TTL=1800 on every request.
  - [ ] Unit: recharge_confirm "1" → recharge command called with correct subscriber_id + plan_id + payment_method_id.
  - [ ] Integration (slow, `@pytest.mark.slow`): testcontainers Postgres + Valkey; full session flow: root → balance → back → recharge_select → confirm → result. [Source: 1-4 story; architecture.md conftest testcontainers]

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
