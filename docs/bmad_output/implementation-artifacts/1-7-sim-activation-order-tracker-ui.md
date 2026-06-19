# Story 1.7: SIM Activation Order Tracker UI

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **new subscriber**,
I want to see a step-by-step visual tracker showing my SIM order's current fulfilment state,
so that I know exactly where I am in the activation process and what to expect next.

## Acceptance Criteria

1. **Given** a logged-in subscriber has an `ops_order_fulfilment` record, **When** they navigate to `/activate`, **Then** a four-step indicator renders the states **Created → KYC Pending → KYC Verified → Activated**, with the current step highlighted and all completed steps showing a checkmark.
2. The tracker polls `GET /api/v1/subscriber/orders/{order_id}/status` every **10 seconds** (polling, NOT WebSocket) and re-renders the step indicator when the returned status advances.
3. **Given** the order `status = 'ACTIVATED'`, **When** the tracker renders, **Then** a success banner is shown displaying the subscriber's MSISDN, and polling stops.
4. The subscriber-facing tracker lives at `frontend/src/portals/subscriber/SimActivation.tsx` (route `/activate`, behind the `/subscriber/*` role guard) and is **read-only** — it never mutates order state.
5. The read endpoint `GET /api/v1/subscriber/orders/{order_id}/status` returns the standard envelope `{data: {...}, meta: {trace_id, timestamp}}` and authorises the caller so a subscriber may only read **their own** order (JWT `sub` claim must match the order's `subscriber_id`); a mismatch returns HTTP 403.
6. A separate **simulator developer tool** at `frontend/src/portals/simulator/SimActivation.tsx` (under `/simulator/*`) lets a developer advance an order's fulfilment state forward through the state machine, by calling a simulator endpoint in `service_webapp/src/routers/simulator.py` that mutates `ops_order_fulfilment`. This is NOT subscriber-facing.

## Tasks / Subtasks

- [ ] **Task 1: Subscriber read endpoint for order status** (AC: #2, #5)
  - [ ] Add `GET /api/v1/subscriber/orders/{order_id}/status` to `service_webapp/src/routers/account.py` (FR-1–7 / Account & Identity grouping — note: an `orders.py` subscriber router is acceptable, but `account.py` is the canonical home per the FR grouping)
  - [ ] Query `ops_order_fulfilment` by `id = {order_id}`; return `{status, msisdn, updated_at}` (MSISDN only populated/decrypted once `status='ACTIVATED'`)
  - [ ] Authorise: the JWT `sub` claim (subscriber UUID, from Story 1.8 `core/auth.py`) must equal the order's `subscriber_id`; otherwise HTTP 403. 404 if the order does not exist
  - [ ] Wrap the response in the standard envelope (`{data, meta:{trace_id, timestamp}}`) per §1.11.3
  - [ ] PII hygiene: do NOT log raw MSISDN; use `msisdn[-4:]`. Do NOT place MSISDN in OTEL span attributes
- [ ] **Task 2: Subscriber tracker component + polling hook** (AC: #1, #2, #3, #4)
  - [ ] Create `frontend/src/portals/subscriber/SimActivation.tsx` (route `/activate`)
  - [ ] Create a `useOrderStatus.ts` hook in `frontend/src/hooks/` using TanStack Query with `refetchInterval: 10000`; stop polling (`refetchInterval: false`) once `status === 'ACTIVATED'`
  - [ ] Render a four-step indicator (Created → KYC Pending → KYC Verified → Activated): current step highlighted; completed steps show a checkmark. Build from shared UI primitives (`Card`, `Badge`) in `frontend/src/components/ui/`
  - [ ] On `status='ACTIVATED'`: render a success banner with the MSISDN; on order-not-found/403: render an inline error state
- [ ] **Task 3: Simulator developer tool to advance order state** (AC: #6)
  - [ ] Add a simulator endpoint to `service_webapp/src/routers/simulator.py` (FR-68–70) that advances a given order's `ops_order_fulfilment.status` forward one step through the state machine (Created → KYC Pending → KYC Verified → Activated)
  - [ ] Create `frontend/src/portals/simulator/SimActivation.tsx` under `/simulator/*` (simulator role guard): a dev control to pick an order and advance its state; reuse `Button`/`Table` from `components/ui/`
  - [ ] State machine guardrails: only forward transitions; reject illegal jumps; setting `ACTIVATED` is the terminal step that assigns/reveals the MSISDN
- [ ] **Task 4: Tests** (AC: #1, #2, #3, #5)
  - [ ] Frontend (Vitest + React Testing Library): mock the polling endpoint and assert the step indicator renders correctly for each of the four states (highlight + checkmark logic); assert the success banner with MSISDN appears on `ACTIVATED`; assert polling stops on `ACTIVATED`
  - [ ] Backend (`service_webapp/tests/unit/`): endpoint returns the envelope; 403 when `sub` ≠ `subscriber_id`; 404 for unknown order; MSISDN absent until `ACTIVATED`

## Dev Notes

### Scope boundary

- **DOES:** subscriber-facing read-only tracker at `/activate` with 10s polling and an ACTIVATED success banner; the read endpoint with own-order authorisation; a simulator dev tool to advance order state for testing.
- **DOES NOT:** implement real KYC verification logic. What actually flips **KYC Pending → KYC Verified** is *simulated/seeded* — driven either by seed data (Epic 2) or by the simulator tool (flow #2 below). Do not build a KYC backend, document upload, or verification service here.
- **DOES NOT:** create any DB migration. `ops_order_fulfilment` already exists in the V1 baseline (Story 1.2). The order **row** is created at registration time by Story 1.6 with initial state `CREATED`.

### RESOLVED — two distinct activation flows (BOTH in scope; this fixes the Story 1.1 open question)

The epics and architecture appeared to conflict on where `SimActivation.tsx` lives. The resolution is that there are **two different screens with the same conceptual name**, and both are real:

| # | Flow | Location | Audience | Behaviour |
|---|------|----------|----------|-----------|
| 1 | **Subscriber tracker (primary)** | `frontend/src/portals/subscriber/SimActivation.tsx`, route `/activate`, `/subscriber/*` guard | Logged-in subscriber | Read-only step tracker, 10s polling, success banner |
| 2 | **Simulator dev tool (secondary)** | `frontend/src/portals/simulator/SimActivation.tsx`, `/simulator/*` guard | Developers (not subscribers) | Advances `ops_order_fulfilment` state forward for testing |

- Architecture §1.12.1's listing of `SimActivation.tsx` under `portals/simulator/` refers to **flow #2** (the dev tool).
- The epics' `frontend/src/pages/subscriber/` path is **corrected** to `frontend/src/portals/subscriber/SimActivation.tsx` (architecture layout wins; `portals/` not `pages/`).
- Story 1.1's UX brief flagged the placement as open "to confirm in Story 1.7" — this is the confirmation: subscriber tracker = `portals/subscriber/`; simulator tool = `portals/simulator/`. [Source: ux-brief-identity.md (Story 1.1, AC #5); epics.md#Story-1.7]

### Canonical order table — `ops_order_fulfilment`

- The epics' `subscriber_order` is **shorthand** for the canonical `ops_order_fulfilment` table (architecture §1.7.1, `ops_` domain). It uses a **UUIDv7** PK (transactional/high-insert). No new table, no migration — it is part of the V1 all-domain baseline. [Source: architecture.md#1.7.1; Story 1.2 RESOLVED V1 scope]
- The fulfilment status column drives the four tracker steps. Status values used here: `CREATED`, `KYC_PENDING`, `KYC_VERIFIED`, `ACTIVATED`. MSISDN is assigned/revealed only at `ACTIVATED`.

### Frontend conventions (architecture layout wins)

- Layout: `src/portals/{subscriber,simulator}/`, shared primitives in `src/components/ui/`, hooks in `src/hooks/` (`usePascalCase.ts`), API in `src/lib/api.ts`. **TailwindCSS utility classes only** — no per-component SCSS/CSS modules; `globals.css` only. Components `PascalCase.tsx`. [Source: architecture.md#1.9.1, #1.11.2, #1.12.1; Story 1.1 RESOLVED conventions]
- **Server state via TanStack Query** — no Redux/global store. Polling is implemented via `refetchInterval`, not a manual `setInterval`. [Source: architecture.md#1.9.3]
- Reuse shared UI (`Button`, `Card`, `Badge`, `Table`, `Modal`) defined in the Story 1.1 UX brief and built in the frontend scaffold — do NOT hand-roll new button/card markup. [Source: ux-brief-identity.md AC #3]
- Polling, not WebSocket: the order tracker is explicitly a 10s poll. WebSocket channels (`useWebSocket.ts`) exist for other features but are NOT used here. [Source: architecture.md#1.9.2; epics.md#Story-1.7]

### Backend & authorisation

- Read endpoint in `service_webapp/src/routers/account.py` (FR-1–7). Standard envelope per §1.11.3 (`data` + `meta.trace_id`/`timestamp`). [Source: architecture.md#1.11.3, #1.12.1]
- Own-order authorisation: compare the JWT `sub` claim (resolved by `core/auth.py`, Story 1.8) to `ops_order_fulfilment.subscriber_id`. Mismatch → 403; unknown order → 404.
- Simulator state-advance endpoint in `routers/simulator.py` (FR-68–70) — forward-only transitions through the state machine.

### Dependencies & prerequisites

- **Story 1.6** — creates the subscriber + the `ops_order_fulfilment` order row (state `CREATED`) at registration. This story consumes that record. [Cross-story]
- **Story 1.8** — JWT auth + `RoleGuard` + `lib/auth.ts` role extraction; required to reach `/activate` (subscriber) and `/simulator/*` (simulator) and to resolve the `sub` claim for own-order authorisation.
- **Story 1.1** — UX brief (design source for the four-step tracker, AC #5) + shared UI component names.
- **Story 1.4** — API envelope + OTEL trace middleware (`meta.trace_id`).

### Project Structure Notes

- New (frontend): `frontend/src/portals/subscriber/SimActivation.tsx`, `frontend/src/portals/simulator/SimActivation.tsx`, `frontend/src/hooks/useOrderStatus.ts`.
- Extends (backend): `service_webapp/src/routers/account.py` (add the order-status route), `service_webapp/src/routers/simulator.py` (add the advance-state route — create the router if it does not yet exist).
- Variance: epics says `pages/subscriber/`; corrected to `portals/subscriber/` per architecture. Epics says `subscriber_order`; corrected to `ops_order_fulfilment`.

### Testing standards summary

- Frontend: Vitest + React Testing Library (no Cypress for MVP). Mock the polling endpoint; assert per-state step rendering, checkmark/highlight logic, ACTIVATED success banner + MSISDN, and that polling halts on ACTIVATED. [Source: architecture.md#1.11.8]
- Backend: pytest via `uv tox`; unit tests in `service_webapp/tests/unit/`. Assert envelope shape, 403 on `sub` mismatch, 404 on unknown order, MSISDN withheld until `ACTIVATED`.
- Python 3.11; lint/format via `ruff`, types via `mypy`, matrix via `uv tox`.

### References

- [Source: epics.md#Story-1.7 (lines 424–442)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (ops_order_fulfilment, lines 357–428)]
- [Source: architecture.md#1.9.1-Single-SPA-Role-Based-Dashboard-Routing (lines 634–645)]
- [Source: architecture.md#1.9.2-Real-Time-UI-Channels (lines 662–671)]
- [Source: architecture.md#1.9.3-State-Management (TanStack Query, no Redux)]
- [Source: architecture.md#1.11.3-API-Response-Format (lines 825–847)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (frontend tree, SimActivation.tsx)]
- [Source: ux-brief-identity.md (Story 1.1 UX brief, AC #5 — four-step tracker, 10s polling)]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
