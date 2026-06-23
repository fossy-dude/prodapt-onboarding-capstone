---
baseline_commit: 50c6cf7982b76a5d338a2d6b7c59f097ee4dca46
---

# Story 3.2: Real-Time Balance Display & Usage Breakdown

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to see my current prepaid wallet balance and per-type usage breakdown on my dashboard,
so that I always know how much credit I have and how I've used my plan allowances.

## Acceptance Criteria

1. **Given** a subscriber is logged in and navigates to `/subscriber/dashboard`, **When** the page loads, **Then** `GET /api/v1/subscriber/balance` returns the current balance in paise, rendered as INR with 2 decimal places (FR-8). [Source: epics.md:1160; prd.md FR-8 (lines 204, 211)]
2. **And** the balance reflects the latest Valkey value (read from `balance:{msisdn}`) — not a stale DB read. [Source: epics.md:1162; architecture.md#1.7.3 (lines 485, 509)]
3. **And** if balance = 0, the UI shows a "Balance depleted" warning banner with a "Recharge Now" CTA (FR-8). [Source: epics.md:1164; prd.md FR-8 (line 212)]
4. **And** `GET /api/v1/subscriber/usage` returns per-type consumption for the current plan period: `voice_minutes_used`, `data_mb_used`, `sms_count_used`, `roaming_mb_used` (FR-10). [Source: epics.md:1166; prd.md FR-10 (line 224, 230)]
5. **And** usage rings display used vs total allowance for each type; "Unlimited" label shown when plan has no cap. [Source: epics.md:1168; prd.md FR-10 (line 231)]
6. **Given** a CDR deduction occurs, **When** the subscriber views the dashboard within 5 seconds, **Then** a manual refresh of the balance API reflects the updated balance. [Source: epics.md:1172]

## Tasks / Subtasks

- [x] **Task 1: Backend balance endpoint** (AC: #1, #2, #3, #6)
  - [x] Create `service_webapp/src/routers/balance.py` with `prefix=/api/v1/subscriber`, `GET /balance`. Guard: `jwt_payload: dict = require_role("subscriber")` (`core/auth.py:129`) **plus** owner assertion `subscriber_id == jwt.sub` via the `_require_sub(jwt_payload)` pattern (`account.py:217-231`). [Source: core/auth.py:129-178; account.py:217-231,260; 1-8 story; deferred-work D3 (require_role not yet wired to production routes)]
  - [x] Read balance from Valkey `balance:{msisdn}` **first** (authoritative, ARCH-6); on cache miss fall back to `billing_wallet_balances.balance_paise` (`V1:162-175`). Return integer paise via `success_envelope(..., trace_id=request.state.trace_id)` (`responses.py:21`). [Source: architecture.md:485, 493-509; 2-3 story (read path); 2-9 story (balance seed)]
  - [x] Add a balance-read helper to `ValkeyAdapter` (`adapters/redis.py:18`) **and** `CacheProtocol` (`core/protocols/cache.py`): `get_balance(msisdn) -> int | None` wrapping `GET` + `int()`. service_webapp has **no** balance reader today. [Source: adapters/redis.py:18-54; 2-3 story; 2-9 story (set_balance pattern)]
  - [x] MSISDN resolution: from JWT `phone_number` (or `identity_subscribers` lookup by `subscriber_id`). [Source: account.py; 1-8 story (JWT payload)]
- [x] **Task 2: Backend usage endpoint** (AC: #4, #5)
  - [x] `GET /usage` in `balance.py`. Active plan via `plans_subscriptions` (`status='active'`, `V1:125-135`) → `start_date..end_date`; SUM per-type usage from the CDR event source for the subscriber in that window. [Source: prd.md FR-10 (lines 224, 230-232); V1:125-135 (plans_subscriptions)]
  - [x] Allowance = `plans_plans` quotas (`voice_minutes`, `data_limit_mb`, `sms_count`, `V1:107-123`); `remaining = allowance − used`; "Unlimited" when quota is null/0 per PRD. [Source: prd.md FR-10 (line 231); V1:107-123]
  - [x] **DATA-SOURCE VERIFICATION:** No `billing_usage_summary` view in V1 migrations. Canonical source is `billing_cdr_events` (status='charged'). Documented in Completion Notes. [Source: architecture.md:443, 1107; 2-2/2-3 stories]
  - [x] `db/billing/queries.py` NEW (read-only CQRS), raw SQL via psycopg3, no ORM. [Source: architecture.md:1112-1113]
- [x] **Task 3: Pydantic models** (AC: #1, #4)
  - [x] Create `service_webapp/src/models/` (NEW dir) with `WalletBalanceResponse` (`subscriber_id`, `msisdn_masked`, `balance_paise`, `balance_inr`, `last_updated_at`) and `UsageResponse` (per-type `{used, allowance, unlimited}` + `plan_period{start,end}`). Suffix `Request`/`Response`/`Schema` per arch §1.11.2. [Source: architecture.md:814; responses.py:21]
- [x] **Task 4: Frontend Dashboard + BalanceCard** (AC: #1, #3, #6)
  - [x] Create `frontend/src/portals/subscriber/Dashboard.tsx` (named export, `readonly Props`, TailwindCSS, ≤200 LOC). Add `<Route path="dashboard">` inside the `/subscriber` `<RoleGuard allowedRoles={['subscriber']}>` (`App.tsx:40-49`). [Source: frontend/CLAUDE.md §2.1, §5.1, §6.1; App.tsx:40-49; 3-1 brief]
  - [x] `BalanceCard`: large INR figure (paise → 2-decimal INR), zero-balance → "Balance depleted" banner + "Recharge Now" CTA (`→ /subscriber/recharge`), last-updated timestamp IST. [Source: epics.md:1134, 1164; 3-1 brief]
  - [x] `lib/api.ts`: `getBalance()` → `apiClient.get('/subscriber/balance')`, unwrap envelope. `hooks/useBalance.ts` (camelCase, ≤100 LOC) via TanStack Query. [Source: lib/api.ts:8; queryClient.ts:6; frontend/CLAUDE.md §2.3]
  - [x] Manual refresh: refetch button / query invalidation (AC #6). [Source: epics.md:1172; prd.md FR-8 (line 210)]
- [x] **Task 5: Frontend UsageRing + charts** (AC: #4, #5)
  - [x] Install `recharts` into `frontend/package.json` (currently absent). Create `frontend/src/components/charts/UsageRing.tsx` (NEW dir): Recharts radial wrapper, props `{used, allowance, unlimited, label}`; "Unlimited" label when unlimited. [Source: epics.md:1136, 1142; architecture.md:1165; frontend/package.json (recharts missing); 3-1 brief]
  - [x] `lib/api.ts` `getUsage()`; `hooks/useUsage.ts`. Dashboard renders one `UsageRing` per type. [Source: epics.md:1166-1168]
- [x] **Task 6: Tests** (AC: #1–#6)
  - [x] Backend unit (httpx.AsyncClient, mocked Valkey + DB): balance hits Valkey (200, paise); Valkey miss → Postgres fallback; `0` → 200 (UI shows banner); usage returns used/allowance per type + Unlimited flag. Auth matrix: subscriber 200, other role 403, no token 401, sub-mismatch 403. [Source: 1-8 story (auth matrix); 1-4 story (testcontainers)]
  - [x] One `slow` integration (testcontainers Postgres + Valkey): real Valkey balance read after a seeded `INCRBY`. [Source: 1-4 story; 2-3 story]
  - [x] Frontend: Vitest + RTL for Dashboard (balance render, zero-banner, rings), `useBalance`/`useUsage` with mocked `apiClient`. [Source: frontend/CLAUDE.md §7]

## Dev Notes

### Scope boundary

- **DOES:** `GET /balance` + `GET /usage` (`balance.py`), `WalletBalance`/`Usage` models, `db/billing/queries.py`, ValkeyAdapter balance read, Dashboard + BalanceCard + UsageRing + hooks, `recharts` dep, tests.
- **DOES NOT:** recharge/balance credit (3-5), transaction ledger (3-3), plan catalogue (3-4), rate limiting (Epic 4), WebSocket push (manual refresh only per AC #6).

### Balance read path — Valkey authoritative (ARCH-6)

`balance:{msisdn}` is a no-TTL integer-paise counter the cdr-pipeline consumer `INCRBY`s (Story 2.3) and the recharge flow credits (Story 3.5). Read Valkey **first**; fall back to `billing_wallet_balances.balance_paise` only if the key is absent (cold cache after restart — `load_balances_from_postgres` repopulates on cdr-pipeline startup). service_webapp currently has **no** balance reader — add it. [Source: architecture.md:485, 493-509; 2-3 story; 2-9 story (set_balance on activation)]

### Money is integer paise

Balance is BIGINT paise in Valkey + `billing_wallet_balances`. Convert to INR (`paise/100`, 2 decimals) only at the presentation boundary. [Source: architecture.md:1233; V1:162-175; 2-3 story]

### Usage data source — verify against the pipeline

Per-type usage (voice/data/SMS/roaming) for the active plan window is aggregated from CDR events. The canonical source is either `billing_cdr_events` (written by Story 2.2) or a `billing_usage_summary` view referenced in architecture (around lines 443/1107). Confirm which exists in migrations and has the per-type fields; prefer the summary view if present. [Source: architecture.md:443, 1107; V1 (verify billing_cdr_events); 2-2/2-3 stories]

### data_gb vs data_limit_mb

`plans_plans` stores `data_limit_mb`; the usage ring + plan card display GB for large values, MB for small (FR-10 "MB/GB"). Expose `data_mb` and a derived `data_gb` from the API. [Source: 3-1 brief variance #1; V1:107-123]

### Auth & owner assertion

`require_role("subscriber")` validates the `cognito:groups` claim but **never** asserts the token `sub`. Use the `_require_sub(jwt_payload)` pattern (`account.py:217-231`) to enforce `subscriber_id == jwt.sub` on every read. [Source: core/auth.py:129-178; account.py:217-231; 1-8 story; deferred-work D3]

### PII

Mask MSISDN to `[-4:]` via `mask_msisdn` (`core/security.py:33-42`) in any response/debug log; never log full MSISDN. [Source: core/security.py:33-42; architecture.md#1.11.6 (line 940); 1-6 story]

### Config & deps

Backend: no new runtime deps (fastapi/psycopg/valkey present). Extend `adapters/redis.py` + `CacheProtocol`; add `routers/balance.py`, `db/billing/queries.py`, `src/models/`. Add new imports to the tox env `deps`. Frontend: ADD `recharts` to `frontend/package.json`. [Source: service_webapp/pyproject.toml; frontend/package.json; app_code_toolchain memory]

### Testing standards summary

Backend: `uv tox lint`/`test`; httpx.AsyncClient with mocked Valkey + DB + role matrix (401/403/200) + one `slow` testcontainers Postgres+Valkey integration. Frontend: `npm run test` (Vitest+RTL), `typecheck`, `lint`; 80% coverage. [Source: service_webapp/pyproject.toml; frontend/CLAUDE.md §7.3; 1-4 story; 1-8 story]

### Project Structure Notes

- **NEW:** `service_webapp/src/routers/balance.py`, `src/models/__init__.py` + balance/usage models, `src/db/billing/queries.py`; `frontend/src/portals/subscriber/Dashboard.tsx`, `src/components/charts/UsageRing.tsx`, `src/hooks/useBalance.ts`, `useUsage.ts`; `recharts` dep.
- **MODIFIES:** `service_webapp/src/adapters/redis.py` (+ `CacheProtocol`) for balance read; `src/main.py` (register balance router); `frontend/src/App.tsx` (`/subscriber/dashboard` route); `frontend/src/lib/api.ts` (`getBalance`, `getUsage`).
- **Variances flagged:** `data_limit_mb` vs `data_gb`; usage data-source verification; `require_role` wiring is NEW (deferred-work D3).

### References

- [Source: epics.md#1.6.2 Story-3.2 (lines 1146-1174)]
- [Source: architecture.md#1.7.3 (485, 493-509), #1.11.2 (814), #1.11.3 (825-847), #1.11.6 (940), #1.12.1 (1144-1174); lines 443, 1052, 1107, 1112-1113]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md FR-8 (204), FR-10 (224), UJ-2 (70)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-123 (plans_plans), 125-135 (plans_subscriptions), 162-175 (billing_wallet_balances)]
- [Source: service_webapp/src/core/auth.py:129-178, core/security.py:33-42, core/responses.py:21, adapters/redis.py:18-54, routers/account.py:217-231,260,307]
- [Source: frontend/src/App.tsx:40-49, lib/api.ts:8, lib/queryClient.ts:6, components/ui/index.ts, CLAUDE.md §2/§5/§6/§7, package.json]
- [Source: 1-4 (testcontainers), 1-6 (mask_msisdn), 1-8 (auth matrix), 2-2/2-3 (balance/CDR contract) stories; deferred-work D3; 3-1 brief]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- ResizeObserver undefined in jsdom: polyfilled in `frontend/src/test/setup.ts`.
- `fastapi.requests.Request` TC002 lint: fixed by importing `Request` from `fastapi` directly (matches account.py pattern).
- `datetime`/`UUID` TC003 in models: suppressed with `# noqa: TC003` (pydantic resolves field types at runtime — cannot use TYPE_CHECKING, per project gotchas memory).
- `DomainError` inline imports PLC0415: fixed by hoisting to top-level import.

### Completion Notes List

- **Usage data source:** No `billing_usage_summary` view exists in V1 migrations. Using `billing_cdr_events` (status='charged') directly via raw SQL in `db/billing/queries.py`.
- **`get_balance` added** to both `CacheProtocol` and `ValkeyAdapter` — service_webapp had no balance reader before this story.
- **MSISDN resolution:** resolved via `billing_wallet_balances` Postgres lookup (not JWT `phone_number`), since the DB row is always fetched first for the cache-fallback path.
- **`data_gb` field:** exposed alongside `data_mb` in `UsageResponse` as `round(data_mb / 1024, 3)` per PRD FR-10 variance.
- **`roaming_mb` unlimited:** always `unlimited=True` (no cap in current plan schema); consistent with PRD "Unlimited" label when quota is null/0.
- **Backend tests:** 13 unit tests pass (all ACs + auth matrix). 1 slow integration test (Postgres+Valkey INCRBY flow).
- **Frontend tests:** 6 Dashboard RTL tests + 2 useBalance + 2 useUsage = 10 new tests. ResizeObserver polyfill added to `src/test/setup.ts` for recharts.
- **All 206 backend unit tests pass; all 112 frontend tests pass. Lint clean.**

### File List

- `service_webapp/src/routers/balance.py` — NEW: GET /balance, GET /usage endpoints
- `service_webapp/src/models/balance.py` — NEW: WalletBalanceResponse, UsageResponse, UsageAllowance, UsagePeriod
- `service_webapp/src/db/__init__.py` — NEW (empty package)
- `service_webapp/src/db/billing/__init__.py` — NEW (empty package)
- `service_webapp/src/db/billing/queries.py` — NEW: read-only CQRS queries (get_wallet_balance_from_db, get_active_subscription, get_usage_for_period, get_msisdn_for_subscriber)
- `service_webapp/src/adapters/redis.py` — MODIFIED: added get_balance() method
- `service_webapp/src/core/protocols/cache.py` — MODIFIED: added get_balance() to CacheProtocol
- `service_webapp/src/main.py` — MODIFIED: import + register balance_router
- `service_webapp/tests/unit/test_balance_endpoint.py` — NEW: 13 unit tests
- `service_webapp/tests/integration/test_balance_integration.py` — NEW: 1 slow integration test
- `frontend/package.json` — MODIFIED: added recharts ^2.14.1
- `frontend/package-lock.json` — MODIFIED: recharts lock entry
- `frontend/src/lib/api.ts` — MODIFIED: getBalance(), getUsage(), WalletBalanceData, UsageData, UsageAllowance types
- `frontend/src/hooks/useBalance.ts` — NEW: useBalance(), useRefreshBalance()
- `frontend/src/hooks/useUsage.ts` — NEW: useUsage()
- `frontend/src/components/charts/UsageRing.tsx` — NEW: Recharts radial ring component
- `frontend/src/portals/subscriber/Dashboard.tsx` — NEW: Dashboard page with BalanceCard + UsageSection
- `frontend/src/App.tsx` — MODIFIED: added /subscriber/dashboard route + Dashboard import
- `frontend/src/test/setup.ts` — MODIFIED: ResizeObserver polyfill for recharts in jsdom
- `frontend/src/portals/subscriber/Dashboard.test.tsx` — NEW: 6 RTL tests
- `frontend/src/hooks/useBalance.test.ts` — NEW: 2 hook tests
- `frontend/src/hooks/useUsage.test.ts` — NEW: 2 hook tests

## Change Log

- 2026-06-23: Story 3.2 implemented — balance/usage API endpoints, Pydantic models, CQRS queries, ValkeyAdapter.get_balance, Dashboard + BalanceCard + UsageRing frontend, recharts dep, 10 new frontend tests, 14 new backend tests (13 unit + 1 slow integration). All ACs satisfied.
