# Story 3.4: Plan Details View & Plan Catalogue

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to view my active plan details and browse all available plans with filter and sort options,
so that I can understand my current entitlements and make informed recharge decisions.

## Acceptance Criteria

1. **Given** a subscriber has an active plan, **When** they view `/subscriber/dashboard`, **Then** a plan details card displays: plan name, validity expiry date in IST format (DD MMM YYYY), bundled quotas (data GB, voice minutes, SMS count), remaining allowances (FR-11). [Source: epics.md:1218; prd.md FR-11 (lines 234, 240-242)]
2. **And** days remaining until expiry is shown as a countdown; plans expiring within 3 days show an amber warning badge. [Source: epics.md:1220]
3. **Given** a subscriber navigates to `/subscriber/plans`, **When** the plan catalogue loads, **Then** `GET /api/v1/plans` returns all active plans with: name, data_gb, voice_minutes, sms_count, validity_days, price_paise, plan_type (FR-12). [Source: epics.md:1226; prd.md FR-12 (lines 252, 259)]
4. **And** the catalogue supports client-side filter by validity (28d / 56d / 84d / all) and sort by price (asc/desc) and data (desc). [Source: epics.md:1228]
5. **And** the subscriber's current active plan is highlighted with a "Current Plan" badge. [Source: epics.md:1230]

## Tasks / Subtasks

- [ ] **Task 1: Backend plan details endpoint** (AC: #1, #2)
  - [ ] `GET /api/v1/subscriber/plan` in `routers/balance.py` (FR-11 per architecture.md:1052). Guard `require_role("subscriber")` + `_require_sub`. [Source: core/auth.py:129; account.py:217-231; architecture.md:1052]
  - [ ] Active plan: `plans_subscriptions WHERE subscriber_id=? AND status='active'` (`V1:125-135`) `JOIN plans_plans` (`V1:107-123`). Return `plan_name`, validity expiry (`end_date`, IST DD MMM YYYY), quotas (`data_limit_mb`→`data_gb`, `voice_minutes`, `sms_count`), `validity_days`, `days_remaining`. [Source: V1:107-135; prd.md FR-11 (line 241)]
  - [ ] Remaining allowances: return **allowance** (quotas) here; the frontend composes used-vs-allowance from `GET /usage` (Story 3.2). Do NOT duplicate usage aggregation. [Source: 3-2 story]
  - [ ] `db/billing/queries.py` (extend). [Source: architecture.md:1112-1113]
- [ ] **Task 2: Backend plan catalogue endpoint** (AC: #3)
  - [ ] `GET /api/v1/plans` in `routers/recharge.py` (FR-12 per architecture.md:1053). Guard `require_role("subscriber")` (shared catalogue data; no owner assertion). [Source: architecture.md:1053; core/auth.py:129]
  - [ ] `SELECT plans_plans WHERE is_active=true` (`V1:107-123`). Return `name` (`plan_name`), `data_gb` (`=data_limit_mb/1024`, round 2), `voice_minutes`, `sms_count`, `validity_days`, `price_paise`, `plan_type` (derived — see variance), `id`. Exclude withdrawn/expired plans per FR-12. [Source: V1:107-123; prd.md FR-12 (line 260)]
  - [ ] `db/recharge/queries.py` NEW (read-only CQRS). [Source: architecture.md:1112-1120]
- [ ] **Task 3: Pydantic models** (AC: #1, #3)
  - [ ] `src/models/ActivePlanResponse` (`plan_id`, `plan_name`, `validity_expiry`, `validity_days`, `days_remaining`, `quotas{data_gb, voice_minutes, sms_count}`, `roaming_enabled`). `PlanCatalogueItem` (`id`, `name`, `data_gb`, `voice_minutes`, `sms_count`, `validity_days`, `price_paise`, `plan_type`). [Source: architecture.md:814]
- [ ] **Task 4: Frontend PlanDetails card** (AC: #1, #2)
  - [ ] `Dashboard.tsx` (extends 3-2) renders a PlanDetails card: plan name, expiry (DD MMM YYYY IST), quotas, remaining allowances (composed from `useUsage`, Story 3-2), days-remaining countdown; amber `Badge` (reuse `components/ui/Badge`) when `days_remaining ≤ 3`. [Source: epics.md:1218-1220; components/ui/index.ts; 3-2 story]
  - [ ] `lib/api.ts` `getActivePlan()`; `hooks/useActivePlan.ts`. [Source: lib/api.ts:8]
- [ ] **Task 5: Frontend Plans catalogue page** (AC: #3, #4, #5)
  - [ ] `frontend/src/portals/subscriber/Plans.tsx` (named export, Tailwind, ≤200 LOC). Route `<Route path="plans">` under `/subscriber` RoleGuard (`App.tsx:40-49`). [Source: frontend/CLAUDE.md; App.tsx:40-49]
  - [ ] `PlanCard` component: plan name, validity badge, data/voice/SMS quota chips, price (INR), "Recharge" CTA (`→ /subscriber/recharge?plan_id={id}`). [Source: epics.md:1138; 3-1 brief]
  - [ ] Client-side filter by validity (28d/56d/84d/all) and sort by price asc/desc + data desc (React state; no backend round-trip). [Source: epics.md:1228]
  - [ ] Current active plan: compare `plan_id` to `useActivePlan().plan_id` → render "Current Plan" `Badge`. [Source: epics.md:1230; components/ui/index.ts]
  - [ ] `lib/api.ts` `listPlans()`; `hooks/usePlans.ts`. [Source: lib/api.ts:8]
- [ ] **Task 6: Tests** (AC: #1–#5)
  - [ ] Backend unit: `/plan` returns active plan + expiry + quotas; no active plan → decide 200-empty vs 404 (document). `/plans` returns only `is_active` plans with `data_gb` conversion. Auth matrix (401/403/200). [Source: 1-8 story; 1-4 story]
  - [ ] Frontend: Vitest + RTL — PlanDetails render + amber badge at ≤3 days; catalogue filter/sort; Current Plan badge. [Source: frontend/CLAUDE.md §7]

## Dev Notes

### Scope boundary

- **DOES:** `GET /subscriber/plan` (active plan), `GET /plans` (catalogue), `ActivePlan`/`PlanCatalogue` models, `db/billing` + `db/recharge` queries, PlanDetails card, Plans page + PlanCard + filter/sort + Current Plan badge, tests.
- **DOES NOT:** usage aggregation (3-2), recharge flow (3-5), receipt (3-6), plan-expiry notifications (Epic 4 FR-20).

### data_gb vs data_limit_mb + plan_type — schema variances

- `plans_plans` stores `data_limit_mb` (`V1:107-123`); API exposes `data_gb = round(data_limit_mb/1024, 2)`. [Source: 3-1 brief variance #1]
- **NO `plan_type`/`category` column.** Derive `plan_type` from `plan_code` (or omit from the card). The catalogue filter is by validity, not `plan_type`. [Source: 3-1 brief variance #2; V1:107-123; architecture.md:1205-1206]
- Money is integer paise (`price_paise`); UI renders INR. [Source: architecture.md:1233]

### Active plan source

`plans_subscriptions` (`V1:125-135`): `subscriber_id`, `plan_id`, `start_date`, `end_date`, `status` default `'active'`. Active = `status='active'`; expiry = `end_date`; `days_remaining = end_date − now` (IST). If multiple active rows exist, pick the latest `start_date` (decide; document). [Source: V1:125-135]

### 3-day amber badge vs Epic 4 notification

The "expiring within 3 days → amber badge" is a **UI-only** affordance here (constant 3). The plan-expiry SMS/push reminder (FR-20, 3-day lead) is Epic 4 (notification service) — out of scope here. [Source: epics.md:1220; prd.md FR-20 (line 340)]

### Remaining allowances come from 3-2

PlanDetails shows remaining = allowance (this endpoint) − used (`GET /usage`, Story 3-2). Do not re-aggregate usage in `/plan`; the card composes `useActivePlan` + `useUsage`. [Source: 3-2 story]

### Auth

`/plan`: `require_role("subscriber")` + `_require_sub`. `/plans`: `require_role("subscriber")` (shared catalogue data, no owner assertion). [Source: core/auth.py:129-178; account.py:217-231; deferred-work D3]

### Project Structure Notes

- **NEW:** `frontend/src/portals/subscriber/Plans.tsx`, `hooks/useActivePlan.ts`, `usePlans.ts`, `PlanCard` component; `service_webapp/src/db/recharge/queries.py`.
- **MODIFIES:** `service_webapp/src/routers/balance.py` (+ `GET /subscriber/plan`), `src/routers/recharge.py` (NEW router, `GET /plans`), `src/models/` (+ActivePlan/PlanCatalogue), `src/db/billing/queries.py`, `src/main.py` (register recharge router), `frontend/src/App.tsx` (`/subscriber/plans` route), `Dashboard.tsx` (+PlanDetails card), `lib/api.ts` (`getActivePlan`, `listPlans`).
- **Variances flagged:** `data_limit_mb`→`data_gb`; `plan_type` derived/omitted; 3-day badge is UI-only (notification is Epic 4); remaining allowances from 3-2.

### References

- [Source: epics.md#1.6.4 Story-3.4 (lines 1204-1230)]
- [Source: architecture.md:1052-1053 (balance.py FR-11, recharge.py FR-12), 1112-1120 (db/billing, db/recharge), 814, 1144-1174, 1205-1206, 1233]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md FR-11 (234), FR-12 (252), UJ-2 (70)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-123 (plans_plans), 125-135 (plans_subscriptions)]
- [Source: service_webapp/src/core/auth.py:129-178; frontend/src/App.tsx:40-49, components/ui/index.ts, lib/api.ts:8]
- [Source: 1-8 (auth), 1-4 (testcontainers), 3-1 (brief), 3-2 (usage), 3-5 (recharge) stories; deferred-work D3]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
