---
baseline_commit: 89d48fe
---

# Story 6.5: SIM Swap & Suspicious Recharge Alerts

Status: ready-for-dev

## Story

As a **fraud analyst**,
I want dedicated alert views for SIM swap patterns and suspicious recharge frequency,
so that high-priority account takeover risks are immediately visible and distinguishable from other fraud types.

## Acceptance Criteria

1. **Given** the Fraud Detection Agent confirms a SIM swap pattern (rule_triggered = `SIM_SWAP`), **When** the `fraud.alerts` event is consumed by the UI WebSocket, **Then** the alert appears in the AnomalyFeed with a red "SIM SWAP" badge. (FR-55) [Source: epics.md:1906]
2. **And** a dedicated filter on `/fraud/cases?type=SIM_SWAP` shows only SIM swap escalations. [Source: epics.md:1908]
3. **Given** the pre-screener detects >3 recharges in 24 hours for a subscriber, **When** the fraud agent confirms suspicious recharge pattern, **Then** the alert appears with an amber "RECHARGE ANOMALY" badge. (FR-56) [Source: epics.md:1914]
4. **And** the case detail view shows the recharge timestamps and amounts. [Source: epics.md:1916]

## Tasks / Subtasks

- [ ] **Task 1: Backend — case detail with recharge history** (AC: #4)
  - [ ] In `service_webapp/src/db/fraud/queries.py` (from 6.3/6.4), add:
    - `get_fraud_case_detail(conn, case_id: UUID) -> dict | None` — joins the case + its recharge history. Returns the case fields (from 6.4 projection) PLUS `recharge_history` when `fraud_type='SUSPICIOUS_RECHARGE'`:
      ```sql
      SELECT id AS case_id, msisdn, verdict, risk_score AS confidence_score,
             status, created_at AS detected_at, fraud_type, triggered_by AS rule_triggered,
             analyst_notes, evidence
      FROM fraud_cases WHERE id = %(case_id)s
      ```
    - `get_case_recharge_history(conn, subscriber_id: UUID) -> list[dict]` —
      ```sql
      SELECT id, plan_id, amount_paise, status, idempotency_key, created_at
      FROM recharge_orders
      WHERE subscriber_id = %(subscriber_id)s
        AND created_at >= NOW() - INTERVAL '7 days'
      ORDER BY created_at DESC
      LIMIT 20
      ```
  - [ ] In `service_webapp/src/routers/fraud.py` (from 6.4), add `GET /api/v1/fraud/cases/{case_id}` — role `fraud`; returns case + `recharge_history` (for SUSPICIOUS_RECHARGE) or the `evidence` JSONB (for other types). Resolve `subscriber_id` from the case to fetch recharge history server-side (do NOT accept a client-supplied subscriber_id — IDOR-safe). MSISDN masked to `[-4:]`.

- [ ] **Task 2: Backend — confirm `?type=` filter semantics** (AC: #2)
  - [ ] The `GET /api/v1/fraud/cases?type=SIM_SWAP` filter is already implemented in 6.4 (`list_fraud_cases` `type_filter`). Verify the filter matches on `fraud_type` (the category column = `SIM_SWAP` / `SUSPICIOUS_RECHARGE` / `VELOCITY` / `GEOGRAPHIC_ANOMALY`) — the same value the pre-screener (6.2) writes to `fraud_events.rule_triggered` and the agent (6.3) copies to `fraud_cases.fraud_type`.
  - [ ] Ensure the rule-type vocabulary is consistent end-to-end: pre-screener seeds `fraud_rules.rule_type ∈ {VELOCITY, GEOGRAPHIC_ANOMALY, SIM_SWAP, SUSPICIOUS_RECHARGE}` (6.2); agent copies that to `fraud_cases.fraud_type`; UI filters on the same strings. No synonyms.

- [ ] **Task 3: Frontend — colored badges in AnomalyFeed** (AC: #1, #3)
  - [ ] Implement the `badgeFor(rule_triggered, verdict)` helper left as a stub in 6.4 `AnomalyFeed.tsx`:
    ```ts
    function badgeFor(rule: string): { label: string; color: "red" | "amber" | null } {
      switch (rule) {
        case "SIM_SWAP":            return { label: "SIM SWAP",          color: "red" };
        case "SUSPICIOUS_RECHARGE": return { label: "RECHARGE ANOMALY",  color: "amber" };
        default:                    return null;
      }
    }
    ```
  - [ ] Render the badge in each feed row. Red uses the danger token; amber the warning token (tailwind `bg-red-100 text-red-800` / `bg-amber-100 text-amber-800` — match existing portal styling, e.g. status chips elsewhere).
  - [ ] The alert payload from `fraud.alerts` (6.3) carries `rule_triggered`; the badge derives from it, so badge correctness depends on the 6.3 publisher including `rule_triggered` in the alert payload — verify in 6.3's publisher (it does).

- [ ] **Task 4: Frontend — dedicated `?type=SIM_SWAP` filter UX** (AC: #2)
  - [ ] In `CaseQueue.tsx` (6.4), add filter chips/buttons: "All", "SIM Swap", "Recharge Anomaly", "Velocity", "Geo". Selecting sets the `type` query param (`SIM_SWAP`, `SUSPICIOUS_RECHARGE`, etc.) and the `FRAUD_CASES_QUERY_KEY` filter state; React Query refetches.
  - [ ] The filter state must survive pagination (cursor) — keep `type` in the query key.
  - [ ] `/fraud/cases?type=SIM_SWAP` deep-link must hydrate the filter from the URL on load (read the search param → set the active chip + query). Use `useSearchParams` (react-router-dom v7).

- [ ] **Task 5: Frontend — case detail view** (AC: #4)
  - [ ] Create `frontend/src/portals/fraud/CaseDetail.tsx` (or a detail panel in CaseQueue): navigated to via `/fraud/cases/:caseId` or a row expand. Fetches `GET /api/v1/fraud/cases/{case_id}`.
  - [ ] For `SUSPICIOUS_RECHARGE` cases, render `recharge_history` as a table: `created_at` (timestamp), `amount_paise` (formatted ₹), `status`, `idempotency_key[-8:]`. Title: "Recharge activity (last 7 days)".
  - [ ] For `SIM_SWAP` cases, render the SIM-swap `evidence` (registration timestamps, sim_serial[-4:]) — masked.

- [ ] **Task 6: Tests** (AC: #1–#4)
  - [ ] `service_webapp/tests/api/test_fraud_case_detail.py`: detail for SUSPICIOUS_RECHARGE includes `recharge_history` (timestamps + amounts); detail for SIM_SWAP includes evidence; detail masks msisdn; `type=SIM_SWAP` filter returns only SIM_SWAP cases; unknown case_id → 404; wrong role → 403.
  - [ ] `frontend/src/portals/fraud/__tests__/AnomalyFeed.test.tsx`: SIM_SWAP alert → red "SIM SWAP" badge; SUSPICIOUS_RECHARGE → amber "RECHARGE ANOMALY" badge; VELOCITY → no badge.
  - [ ] `frontend/src/portals/fraud/__tests__/CaseQueue.test.tsx`: filter chip sets query param; deep-link `?type=SIM_SWAP` hydrates filter; filter preserved across "load more".
  - [ ] Integration (`@pytest.mark.slow`): seed a SUSPICIOUS_RECHARGE fraud_case + matching recharge_orders rows; assert detail returns them.

## Dev Notes

### 6.5 is a frontend-leaning extension of 6.4

The feed (6.4) already renders `rule_triggered`; 6.4's `badgeFor` returns null. 6.5 fills it. The `GET /api/v1/fraud/cases?type=` filter is already end-to-end in 6.4; 6.5 adds the UI chips + deep-link hydration + a case detail endpoint. Do NOT re-implement the feed or queue. [Source: 6-4 dev notes "6.5 extension points"; epics.md 6.5]

### Rule-type vocabulary must be identical end-to-end

The badge + filter both key off the rule_type string. It must be the SAME string everywhere:
- `fraud_rules.rule_type` seed (6.2): `VELOCITY`, `GEOGRAPHIC_ANOMALY`, `SIM_SWAP`, `SUSPICIOUS_RECHARGE`.
- `fraud_events.rule_triggered` (6.2) + `fraud.alerts` payload `rule_triggered` (6.3) + `fraud_cases.fraud_type` (6.3) all copy that exact string.
- Frontend badge/filter match on these literals.
No `sim-swap` / `SimSwap` / `SIMSWAP` drift anywhere. [Source: 6-2 fraud_rules seed; epics.md 6.5 AC]

### Case detail must be IDOR-safe

`GET /api/v1/fraud/cases/{case_id}` resolves `subscriber_id` from the case row server-side, then fetches recharge history. Never accept `subscriber_id`/`msisdn` from the client request. (Epic-5 IDOR lesson — though this is an analyst endpoint, not subscriber-facing, the principle holds: server resolves identity.) [Source: 5-4/5-6 IDOR lesson; 6-3 dev notes]

### recharge_orders columns

`recharge_orders` (V1): `id, subscriber_id, plan_id, amount_paise, idempotency_key, status, created_at, ...` (append-only). Use `amount_paise` (paise → ₹ = `paise/100`), `created_at`, `idempotency_key`. `status` values include `COMPLETED`. The pre-screener (6.2) suspicious-recharge rule already counts these. [Source: V1__baseline_schema.sql; 6-2 dev notes]

### Badge colors — match existing portal styling

tailwind classes (`bg-red-100 text-red-800 border-red-200` / `bg-amber-100 text-amber-800 border-amber-200`). If existing portal status chips use a shared `Badge` component in `components/ui/`, reuse it with a `tone` prop instead of bespoke classes. [Source: UX-DR8; frontend/components/ui/]

### deep-link hydration — react-router v7

`/fraud/cases?type=SIM_SWAP` must hydrate the filter on load. Use `useSearchParams()` from `react-router-dom` (v7.1.0 per package.json). Keep `type` in both the URL and the `FRAUD_CASES_QUERY_KEY` so refresh/share preserves the filter. [Source: frontend/package.json]

### Project Structure Notes

- Extended backend: `service_webapp/src/db/fraud/queries.py` (get_fraud_case_detail, get_case_recharge_history), `service_webapp/src/routers/fraud.py` (GET /fraud/cases/{case_id})
- New frontend: `frontend/src/portals/fraud/CaseDetail.tsx`; modified `AnomalyFeed.tsx` (badgeFor), `CaseQueue.tsx` (filter chips + deep-link), `types/fraud.ts` (detail types)
- New tests: `tests/api/test_fraud_case_detail.py`, frontend vitest specs for badges/filter/detail
- No new migration. No agent changes. No cdr-pipeline changes.

### References

- [Source: epics.md:1892-1916 — Story 6.5 acceptance criteria]
- [Source: epics.md#1.2.2 FR-55, FR-56 — SIM swap + suspicious recharge alerts]
- [Source: architecture.md#1.9.2 — anomaly feed; §1.12.1 portals/fraud/]
- [Source: V1__baseline_schema.sql — recharge_orders columns; fraud_cases DDL]
- [Source: 6-2-eval.../6-2-rule-based-cdr-pre-screener.md — rule_type vocabulary, fraud_rules seed]
- [Source: 6-3-fraud-detection-agent-llm-powered-risk-analysis.md — fraud_cases.fraud_type copy, evidence JSONB]
- [Source: 6-4-...md — badgeFor stub, ?type filter, AnomalyFeed/CaseQueue]
- [Source: frontend/package.json — react-router-dom v7, tailwind]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
