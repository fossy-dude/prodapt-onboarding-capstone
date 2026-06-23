---
baseline_commit: a90c558
---

# Story 3.3: Transaction History Ledger

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to view a paginated list of all my charges, recharges, and refunds with timestamps and CDR references,
so that I can audit my account activity and understand every deduction.

## Acceptance Criteria

1. **Given** a subscriber navigates to `/subscriber/history`, **When** the page loads, **Then** `GET /api/v1/subscriber/transactions` returns a paginated ledger (default 20 rows/page) of: `transaction_type` (CHARGE | RECHARGE | REFUND), `amount_paise`, `balance_after_paise`, `cdr_reference` (nullable), `description`, `created_at` (FR-9). [Source: epics.md:1192; prd.md FR-9 (lines 214, 220)]
2. **And** entries are sorted by `created_at` descending (newest first). [Source: epics.md:1194; prd.md FR-9 (line 221)]
3. **And** the UI supports page navigation (prev/next) via React Query with cursor-based pagination. [Source: epics.md:1196]
4. **And** each CHARGE row displays the CDR reference as a copyable code. [Source: epics.md:1198]
5. **And** the ledger is immutable — no edit or delete UI exists (FR-9). [Source: epics.md:1200; prd.md FR-9 (line 222)]

## Tasks / Subtasks

- [x] **Task 1: Backend transactions endpoint** (AC: #1, #2)
  - [x] `GET /transactions` in `service_webapp/src/routers/balance.py` (FR-9 belongs to `balance.py` per architecture.md:1052). Guard `require_role("subscriber")` + `_require_sub` owner assertion. [Source: core/auth.py:129; account.py:217-231; architecture.md:1052]
  - [x] Read `billing_transactions` (`V1:218-230`, append-only) `WHERE subscriber_id=? ORDER BY created_at DESC, id DESC` via `db/billing/queries.py` (extend; CQRS read-only). [Source: V1:218-230; architecture.md:1112-1113]
  - [x] Cursor pagination: accept `?cursor=<id>&page_size=20` (default 20 — **epic-driven**, not in PRD). Cursor = last `id` of prior page (UUIDv7 is time-monotonic). Return `items` + `next_cursor` (null when exhausted). [Source: epics.md:1192, 1196; prd.md FR-9 (line 221)]
  - [x] `cdr_reference` mapping: no `cdr_reference` column — derive as `reference_id` WHERE `reference_type='cdr'`, else null. [Source: V1:218-230 (reference_type, reference_id)]
  - [x] `transaction_type` values: emit the **same strings the writers use** (2-3 deduction; 3-5 recharge). Verify case against 2-3's INSERT — recommend lowercase `charge|recharge|refund` storage with uppercase display, but reader + both writers MUST agree. [Source: V1:218-230; 2-3 story; 3-5 story]
- [x] **Task 2: Pagination envelope** (AC: #3)
  - [x] Extend `success_envelope` (or `_meta`, `responses.py:17`) to carry `next_cursor` in `meta: {trace_id, next_cursor}`. Keep `data` = items array. [Source: responses.py:17, 21; architecture.md#1.11.3 (825-847)]
- [x] **Task 3: Pydantic model** (AC: #1)
  - [x] `src/models/TransactionItem` (`transaction_type`, `amount_paise`, `balance_after_paise`, `cdr_reference: str | None`, `description`, `created_at`, `id`). [Source: architecture.md:814]
- [x] **Task 4: Frontend History page** (AC: #1, #3, #4, #5)
  - [x] `frontend/src/portals/subscriber/Transactions.tsx` (named export, Tailwind, ≤200 LOC). Route `<Route path="history">` under `/subscriber` RoleGuard (`App.tsx:40-49`). [Source: frontend/CLAUDE.md; App.tsx:40-49]
  - [x] Render via `components/ui/Table` (+`TableColumn`). `useTransactions` hook (TanStack Query cursor pagination: `useInfiniteQuery` or page state driving `getTransactions({cursor})`). Prev/Next buttons; "Next" disabled when `next_cursor` is null. [Source: components/ui/index.ts; queryClient.ts:6; epics.md:1196]
  - [x] CHARGE rows: `cdr_reference` rendered as a copyable code (`navigator.clipboard` + "Copied" toast). Null `cdr_reference` (RECHARGE/REFUND) shows "—". [Source: epics.md:1198]
  - [x] No edit/delete controls (immutable ledger). [Source: epics.md:1200]
  - [x] `lib/api.ts` `getTransactions({cursor, page_size})`. [Source: lib/api.ts:8]
- [x] **Task 5: Tests** (AC: #1–#5)
  - [x] Backend unit: seeded `billing_transactions` → 200, DESC order, `page_size` respected, `next_cursor` correct, `cdr_reference` derived from `reference_id` where `reference_type='cdr'`. Auth matrix (401/403/200) + cross-subscriber 403. [Source: 1-8 story; 1-4 story]
  - [x] Frontend: Vitest + RTL — table render, cursor pagination prev/next, copyable CDR code, no edit/delete affordance. [Source: frontend/CLAUDE.md §7]

## Dev Notes

### Scope boundary

- **DOES:** `GET /transactions` (cursor pagination), `TransactionItem` model, `db/billing/queries` read, pagination meta, History page + `useTransactions` + Table, copyable CDR ref, tests.
- **DOES NOT:** write path (2-3 deduction, 3-5 recharge write here), refund/FAILED filter (3-7 extends this endpoint), rate limiting (Epic 4).

### billing_transactions is append-only — schema gaps vs epic AC

- Columns (`V1:218-230`): `id` (UUIDv7), `subscriber_id`, `transaction_type VARCHAR(20)`, `amount_paise BIGINT`, `reference_type`, `reference_id UUID`, `description`, `balance_before_paise`, `balance_after_paise`, `created_at`.
- **NO `cdr_reference` column** → map `cdr_reference = reference_id` WHERE `reference_type='cdr'` (else null). [Source: V1:218-230]
- **NO `status` column** → the "FAILED" concept in Story 3-7 does **not** live here; 3-7 reads `recharge_orders` instead. This story returns CHARGE/RECHARGE/REFUND rows only. [Source: epics.md:1192; 3-7 story]
- Append-only (`V2` excludes it from the `modified_at` trigger) — no UPDATE/DELETE path, matching AC #5 immutability. [Source: V2__modified_at_trigger.sql:3]

### Cursor pagination contract (story-defined — architecture is SILENT)

Architecture only specifies `?page_size` naming (architecture.md:804). This story defines: `?cursor=<uuid7>&page_size=<n>`, `ORDER BY created_at DESC, id DESC`, `next_cursor` = last row's `id` (null when fewer than `page_size` returned). Default `page_size=20` is epic-driven (FR-9 PRD only says "paginated"). [Source: architecture.md:804; epics.md:1192; prd.md FR-9 (line 221)]

### transaction_type case — must match writers

`billing_transactions.transaction_type` is free-text VARCHAR(20). The deduction writer (2-3) and recharge writer (3-5) emit the values this reader returns. Verify the exact strings (recommend lowercase `charge|recharge|refund` to match codebase conventions) and ensure reader + both writers agree. Document in Completion Notes. [Source: V1:218-230; 2-3 story; 3-5 story]

### Auth & owner assertion

`require_role("subscriber")` + `_require_sub` (`subscriber_id == jwt.sub`). [Source: core/auth.py:129-178; account.py:217-231; 1-8 story; deferred-work D3]

### Project Structure Notes

- **NEW:** `frontend/src/portals/subscriber/Transactions.tsx`, `hooks/useTransactions.ts`.
- **MODIFIES:** `service_webapp/src/routers/balance.py` (+ `GET /transactions`), `src/db/billing/queries.py` (transactions read), `src/core/responses.py` (`next_cursor` in meta), `frontend/src/App.tsx` (`/subscriber/history` route), `lib/api.ts` (`getTransactions`).
- **Variances flagged:** no `cdr_reference`/`status` columns (derived/absent); cursor contract story-defined; `transaction_type` case must match writers; 3-7 will add `?type=FAILED` to this endpoint.

### References

- [Source: epics.md#1.6.3 Story-3.3 (lines 1178-1200)]
- [Source: architecture.md:804 (page_size), 1052 (balance.py=FR-9), 1112-1113 (db/billing/queries), #1.11.3 (825-847), #1.12.1 (1144-1174)]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md FR-9 (214-222), UJ-2 (70)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:218-230 (billing_transactions); V2__modified_at_trigger.sql:3 (append-only)]
- [Source: service_webapp/src/core/auth.py:129-178, core/responses.py:17, 21, routers/account.py:217-231; frontend/src/App.tsx:40-49, components/ui/index.ts, lib/api.ts:8]
- [Source: 1-8 (auth matrix), 1-4 (testcontainers), 2-3 (writer), 3-5 (writer), 3-7 (extends endpoint) stories; deferred-work D3]

## Dev Agent Record

### Agent Model Used

GLM-5.2

### Debug Log References

- Backend (delivered by Phase 1 commit `a90c558`): `service_webapp` unit suite —
  201 passed, including `tests/unit/test_transactions_endpoint.py` (10) and
  `tests/unit/test_plan_details_endpoint.py` (6). ruff + pyrefly clean.
- Frontend (this story): `npm run test` → 118 passed (112 existing + 6 new in
  `Transactions.test.tsx`). `npm run typecheck` clean, `npm run lint` clean,
  prettier `--check` clean.

### Completion Notes List

- **Backend (Tasks 1-3, 5-backend)** delivered by the shared Phase 1 foundation
  (`a90c558`): `GET /api/v1/subscriber/transactions` in `routers/balance.py`
  (keyset cursor paging on UUIDv7 `id`, `page_size` default 20 / max 100,
  `require_role("subscriber")` + `_require_sub` owner assertion);
  `get_transactions_page` in `db/billing/queries.py`; `next_cursor` support in
  `core/responses.py` (sentinel-gated, backward compatible); `TransactionItem`
  in `models/transaction.py`; 10 backend unit tests
  (`test_transactions_endpoint.py`).
- **`transaction_type` variance (resolved per the story's "reader matches writer"
  rule):** the cdr-pipeline deduction writer (Story 2-3,
  `cdr-pipeline/src/consumer/balance_writer.py`) stores the literal `'cdr_deduction'`
  (not `'charge'`), with `reference_type='cdr'`. The reader returns the stored
  value verbatim — reader and writer agree by construction. The AC's
  `CHARGE|RECHARGE|REFUND` is the conceptual category; the frontend maps known
  raw values to friendly labels and keys CDR-copyability off a non-null
  `cdr_reference` (derived from `reference_id` where `reference_type='cdr'`),
  which is robust to the raw type string. Future writers (3-5 recharge, 3-7
  refund) must emit their own consistent values.
- **`cdr_reference` derivation** lives in the endpoint (Python), not SQL, so it is
  covered by unit tests with fakes; raw SQL cursor/ordering is covered separately
  by the (opt-in) integration suite.
- **Frontend (Task 4, 5-frontend)** delivered by this worktree:
  `Transactions.tsx` (named export, Tailwind, ~145 LOC) renders the ledger via
  `components/ui/Table` with columns Type / Description / Amount / Balance After /
  CDR Reference / Date; CDR rows render a copyable code (`navigator.clipboard` +
  transient "Copied!" inline state), non-CDR rows show an em-dash; Prev/Next
  paging with Next disabled when `nextCursor` is null and Prev disabled on the
  first page; no edit/delete affordance (AC #5). `useTransactions.ts` (≤100 LOC)
  drives TanStack Query with a cursor stack so Prev is well-defined.
- **Cross-subscriber isolation** is inherent: `subscriber_id` always comes from
  the JWT `sub` (`_require_sub`), never from the request, so a subscriber can
  only read their own ledger (verified by `test_transactions_scoped_to_jwt_sub`).

### File List

Delivered by Phase 1 commit `a90c558` (shared foundation):

- `service_webapp/src/core/responses.py` (modified — `next_cursor` meta)
- `service_webapp/src/db/billing/queries.py` (modified — `get_transactions_page`)
- `service_webapp/src/routers/balance.py` (modified — `GET /transactions`)
- `service_webapp/src/models/transaction.py` (new — `TransactionItem`)
- `service_webapp/tests/unit/test_transactions_endpoint.py` (new — 10 tests)
- `frontend/src/lib/api.ts` (modified — `getTransactions`)
- `frontend/src/App.tsx` (modified — `/subscriber/history` route)

Delivered by this story's worktree (`work/story-3.3`):

- `frontend/src/hooks/useTransactions.ts` (new)
- `frontend/src/portals/subscriber/Transactions.tsx` (replaced stub with real impl)
- `frontend/src/portals/subscriber/Transactions.test.tsx` (new — 6 tests)

## Change Log

- 2026-06-23: Story 3.3 implemented — transaction history ledger. Backend
  (endpoint, cursor paging, `cdr_reference` derivation, model, tests) delivered
  via shared foundation commit `a90c558`; frontend page + `useTransactions` hook +
  Vitest/RTL tests delivered in this worktree. `transaction_type` returned as the
  raw writer value (`cdr_deduction`); `cdr_reference` derived from
  `reference_type='cdr'`. Story status → review.
