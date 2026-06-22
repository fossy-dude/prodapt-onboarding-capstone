# Story 3.7: Refund View

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to view a list of my failed recharge transactions that would be eligible for refund,
so that I know which transactions did not complete and can follow up if needed.

## Acceptance Criteria

1. **Given** a subscriber navigates to `/subscriber/history` and filters by type = REFUND_ELIGIBLE, **When** the page renders, **Then** `GET /api/v1/subscriber/transactions?type=FAILED` returns all failed recharge transactions for the subscriber (FR-17). [Source: epics.md:1312; prd.md FR-17 (lines 300, 306)]
2. **And** each row shows: `transaction_id`, `plan_attempted`, `amount_paise`, `failure_reason`, `created_at`. [Source: epics.md:1314]
3. **And** a banner states: "Actual refund processing is handled by the operator's billing team. Contact support for assistance." [Source: epics.md:1316]
4. **And** no "Request Refund" button exists — actual refund processing is out of MVP scope (FR-17). [Source: epics.md:1318; prd.md FR-17 (lines 307, 309)]

## Tasks / Subtasks

- [ ] **Task 1: Backend `?type=FAILED` branch** (AC: #1, #2)
  - [ ] Extend `GET /api/v1/subscriber/transactions` (`routers/balance.py`, from 3-3) with a `?type=FAILED` branch. When `type=FAILED` → query `recharge_orders WHERE subscriber_id=? AND status='failed' JOIN plans_plans` (`plan_attempted = plan_name`). Return `{transaction_id (recharge_orders.id), plan_attempted, amount_paise, failure_reason, created_at}`. [Source: epics.md:1312-1314; V1:276-290 (recharge_orders), 107-123 (plans); 3-3 story]
  - [ ] The default branch (no `type` / `type=CHARGE|RECHARGE|REFUND`) continues to read `billing_transactions` (3-3). `FAILED` is a separate axis on `recharge_orders`, NOT `billing_transactions` (which has no `status`). [Source: V1:218-230 (no status); 3-3 story]
  - [ ] `db/billing/queries.py` (extend) + `db/recharge/queries.py` (failed-orders read). [Source: architecture.md:1112-1120]
- [ ] **Task 2: `failure_reason` column** (AC: #2)
  - [ ] `recharge_orders` has NO `failure_reason` column (`V1:276-290`). Add `V4` migration: `ALTER TABLE recharge_orders ADD COLUMN failure_reason TEXT NULL`. Set by the recharge flow on payment failure (3-5 simulates success, so failures populate only when a failure path exists — see Dev Notes). [Source: V1:276-290; 3-5 story]
- [ ] **Task 3: Pydantic model** (AC: #2)
  - [ ] `src/models/FailedRechargeItem` (`transaction_id`, `plan_attempted`, `amount_paise`, `failure_reason: str | None`, `created_at`). [Source: architecture.md:814]
- [ ] **Task 4: Frontend refund-eligible view** (AC: #1, #3, #4)
  - [ ] `Transactions.tsx` (extends 3-3): add a filter control labelled "Refund-eligible" (`type=FAILED`). When active, call `getTransactions({type:'FAILED'})` and render the failed-recharge shape. [Source: epics.md:1308, 1312; 3-3 story; lib/api.ts:8]
  - [ ] Static banner: "Actual refund processing is handled by the operator's billing team. Contact support for assistance." [Source: epics.md:1316]
  - [ ] **NO "Request Refund" button anywhere** (FR-17 out of scope). [Source: epics.md:1318]
  - [ ] `lib/api.ts` `getTransactions({type:'FAILED'})` (extend the 3-3 signature). [Source: lib/api.ts:8]
- [ ] **Task 5: Tests** (AC: #1–#4)
  - [ ] Backend unit: `?type=FAILED` → 200, returns failed `recharge_orders` (joined `plan_attempted`), `failure_reason`; default type → `billing_transactions` (3-3 shape); empty list when no failures; auth matrix. [Source: 1-8 story]
  - [ ] Frontend: Vitest + RTL — REFUND_ELIGIBLE filter toggles `type=FAILED`; banner renders; no refund button. [Source: frontend/CLAUDE.md §7]

## Dev Notes

### Scope boundary

- **DOES:** `?type=FAILED` branch on `GET /transactions` (reads `recharge_orders.status='failed'`), V4 `failure_reason` column, `FailedRechargeItem` model, refund-eligible filter + banner + no-refund-button in `Transactions.tsx`, tests.
- **DOES NOT:** actual refund processing/initiation (FR-17 explicitly out of MVP), recharge write/failure injection (3-5), `billing_transactions` writes.

### FAILED reads recharge_orders, NOT billing_transactions

`billing_transactions` (`V1:218-230`) has NO `status` column and never represents a failed recharge (a failed payment credits nothing, so no ledger row). The "refund-eligible" set = `recharge_orders WHERE status='failed'`. This is a different source than the 3-3 ledger; the endpoint branches on `?type=`. [Source: V1:218-230, 276-290; 3-3 story; prd.md FR-17 (line 306)]

### failure_reason needs a V4 migration

`recharge_orders` (`V1:276-290`) has `status` (default `'pending'`) but no `failure_reason`. Add `failure_reason TEXT NULL` via a new `V4` migration. The recharge flow (3-5) sets `status='failed'` + `failure_reason` only when a payment-failure path exists. [Source: V1:276-290; 3-5 story]

### Simulated-success MVP → list is typically empty

With FR-14 simulated payment (always succeeds, 3-5), recharges do not fail in the current MVP, so the FAILED list is usually empty. The view + banner are the deliverable; rows appear once a failure path exists (real gateway or failure-injection in a later epic). Document this in Completion Notes. [Source: prd.md FR-14 (lines 278-279); 3-5 story; epics.md:1318]

### UI label vs API param

The UI filter is labelled "Refund-eligible" (`REFUND_ELIGIBLE`); the API param is `type=FAILED`. `type=FAILED` maps to the refund-eligible set. [Source: epics.md:1308, 1312]

### No refund initiation (FR-17)

AC #4 + FR-17: no "Request Refund" button, no refund workflow. This view is read-only. [Source: epics.md:1318; prd.md FR-17 (lines 307, 309)]

### Auth & owner assertion

`require_role("subscriber")` + `_require_sub` on the failed-orders read. [Source: core/auth.py:129-178; account.py:217-231; deferred-work D3]

### Project Structure Notes

- **NEW:** `service_webapp/db/migrations/V4__recharge_failure_reason.sql`; `src/models/FailedRechargeItem`.
- **MODIFIES:** `service_webapp/src/routers/balance.py` (+ `?type=FAILED` branch on `GET /transactions`), `src/db/recharge/queries.py` (failed-orders read), `frontend/src/portals/subscriber/Transactions.tsx` (refund-eligible filter + banner), `lib/api.ts` (`getTransactions` `type` param).
- **Variances flagged:** `FAILED` reads `recharge_orders` (not `billing_transactions`); `failure_reason` needs V4 migration; simulated-success MVP → empty list; no refund button (FR-17).

### References

- [Source: epics.md#1.6.7 Story-3.7 (lines 1298-1318)]
- [Source: architecture.md:1052 (balance.py), 1112-1120, 814, 1144-1174]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md FR-17 (300-309), FR-14 (272), UJ-2 (70)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:218-230 (billing_transactions, no status), 276-290 (recharge_orders), 107-123 (plans)]
- [Source: service_webapp/src/core/auth.py:129-178; frontend/src/App.tsx:40-49, lib/api.ts:8]
- [Source: 1-8 (auth), 3-3 (transactions endpoint extended), 3-5 (recharge/failure path) stories; deferred-work D3]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
