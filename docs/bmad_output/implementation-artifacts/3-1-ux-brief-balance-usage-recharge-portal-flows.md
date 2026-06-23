---
baseline_commit: c733cba2bf6cf9cddd3ea4f14bdd7538e42f69e5
---

# Story 3.1: UX Brief — Balance, Usage & Recharge Portal Flows

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **product team**,
I want a lightweight UX brief defining screen layouts, component names, and key interactions for the subscriber self-care portal (balance, usage, plans, recharge, history, receipts),
so that the Epic 3 frontend stories (3.2–3.7) have a clear, agreed-upon design target and the developer agent implements consistent, named components.

## Acceptance Criteria

1. **Given** PRD user journey UJ-2 defines the self-care portal flows, **When** the UX brief is produced, **Then** it documents routes and screen names: `/subscriber/dashboard` (balance card + usage rings), `/subscriber/plans` (catalogue with filter/sort), `/subscriber/recharge` (plan select → payment → confirmation), `/subscriber/history` (transaction ledger), `/subscriber/receipts/{id}` (PDF download). [Source: epics.md#1.6.1 (lines 1128-1132)]
2. It specifies the balance card component: large INR balance figure, zero-balance warning state, last-updated timestamp. [Source: epics.md:1134]
3. It defines usage breakdown display: circular progress rings per type (voice minutes, data MB/GB, SMS count, roaming). [Source: epics.md:1136]
4. It specifies the plan catalogue card: plan name, validity badge, data/voice/SMS quota chips, price, "Recharge" CTA. [Source: epics.md:1138]
5. It defines the recharge flow: Step 1 (plan select), Step 2 (payment method select or add new), Step 3 (confirmation + PDF download link). [Source: epics.md:1140]
6. It names the shared chart component to be created in `frontend/src/components/charts/`: `UsageRing` (Recharts wrapper) (UX-DR2, UX-DR8), and the brief is committed at `docs/bmad_output/planning-artifacts/ux-brief-portal.md` and referenced by stories 3.2–3.7. [Source: epics.md:1142]

## Tasks / Subtasks

- [x] **Task 1: Author the UX brief document** (AC: #1, #6)
  - [x] Create `docs/bmad_output/planning-artifacts/ux-brief-portal.md`.
  - [x] Add a "Document Status" header block matching `ux-brief-identity.md` (fields: `Type`, `Story`, `Produced`, `Authoritative for` = "Epic 3 frontend stories 3.2–3.7") plus a one-line "supersedes any conflicting frontend conventions for these flows" note. [Source: ux-brief-identity.md#Document-Status; 1-1 story Task 1]
  - [x] Use the same single-level decimal section numbering scheme (`1.`, `2.`, `2.1`, …) as `ux-brief-identity.md`. Do not invent new top-level section styles.
- [x] **Task 2: Document the route table** (AC: #1)
  - [x] §1 Screen / Route Table with columns `| Screen Name | Route | Portal Prefix | Purpose |` for the five routes (Dashboard, Plans, Recharge, History, Receipt). Mirror the table shape from `ux-brief-identity.md` §1.
  - [x] Reference (do not redefine) adjacent routes already established by earlier stories: `/subscriber/profile` (Story 1.9), `/subscriber/payment-methods` (Story 1.10), `/subscriber/activate` (Story 1.7), `/subscriber/orders/{id}/status` (Story 1.7).
- [x] **Task 3: Confirm role gating & layout** (AC: #1)
  - [x] §2 restate: the `/subscriber/*` subtree is gated by `<RoleGuard allowedRoles={['subscriber']}>`; the role comes from the JWT `cognito:groups` claim = `"subscriber"`. Pages live in `frontend/src/portals/subscriber/`. [Source: frontend/src/App.tsx:40-49; architecture.md#1.9.1 (lines 639, 645); 1-8 story (subscriber role string)]
- [x] **Task 4: Specify shared UI + chart components** (AC: #3, #6)
  - [x] §3 Shared UI Component Library — reuse the existing `components/ui/` barrel (`Badge`, `Button`, `Card`, `Table`). [Source: frontend/src/components/ui/index.ts]
  - [x] Name NEW primitives the recharge form needs: `Modal`, `Input`, `Select` (none exist today) → target `frontend/src/components/ui/`. [Source: frontend/src/components/ui/ (only Badge/Button/Card/Table present); frontend/CLAUDE.md §2.1]
  - [x] Name the NEW chart component `UsageRing` at `frontend/src/components/charts/UsageRing.tsx` — a Recharts radial/pie wrapper showing used-vs-allowance per type. Note `recharts` is NOT yet installed (dependency added in Story 3.2) and the `components/charts/` directory does not yet exist. [Source: epics.md:1142; architecture.md:1165 (components/charts Recharts wrappers); frontend/package.json (recharts absent)]
  - [x] Restate naming/styling rules: PascalCase `.tsx` components, camelCase hooks, TailwindCSS utility classes only. [Source: frontend/CLAUDE.md §2.1, §6.1]
- [x] **Task 5: Specify the BalanceCard + UsageRing** (AC: #2, #3)
  - [x] BalanceCard: large INR figure (2 decimals, rendered from integer paise), zero-balance → "Balance depleted" warning banner + "Recharge Now" CTA, last-updated timestamp (IST). Data source: `GET /api/v1/subscriber/balance` (Story 3.2). [Source: epics.md:1134; prd.md FR-8 (lines 204, 211-212); 3-2 story]
  - [x] UsageRing: one ring per type (voice minutes, data MB/GB, SMS count, roaming) showing used vs total allowance; "Unlimited" label when the plan has no cap. Data source: `GET /api/v1/subscriber/usage` (Story 3.2). [Source: epics.md:1136; prd.md FR-10 (lines 224, 230-232); 3-2 story]
- [x] **Task 6: Specify the PlanCard (catalogue)** (AC: #4)
  - [x] PlanCard: plan name, validity badge (e.g. "28 days"), data/voice/SMS quota chips, price (INR), "Recharge" CTA → navigates to `/subscriber/recharge?plan_id={id}`. The subscriber's current active plan shows a "Current Plan" badge (reuse `components/ui/Badge`). [Source: epics.md:1138; prd.md FR-12 (lines 252, 258-260); 3-4 story]
- [x] **Task 7: Specify the 3-step Recharge flow** (AC: #5)
  - [x] Step 1 — plan select (pre-selected when `?plan_id=` query param is present).
  - [x] Step 2 — payment method: choose a saved method (`GET /api/v1/subscriber/payment-methods`, Story 1.10) or add a new one. Tokenisation happens browser-side (`frontend/src/lib/tokenize.ts` `tokenizeCard`); raw PAN never leaves the browser (FR-64). [Source: prd.md FR-14 (lines 272, 278-280), FR-64 (lines 815, 821-822); 1-10 story (token-only contract, tokenize.ts)]
  - [x] Step 3 — confirmation: show new balance + plan activation timestamp + a PDF receipt download link (`receipt_url` → Story 3.6). [Source: epics.md:1140; prd.md FR-13 (lines 262, 268-269); 3-5/3-6 stories]
- [x] **Task 8: Add Project Structure Notes / conflict callout** (AC: #6)
  - [x] §7 conflict-resolution table mirroring `ux-brief-identity.md` §7.2: architecture layout (`portals/subscriber/`, `components/ui/`, `components/charts/`, TailwindCSS) is authoritative. [Source: ux-brief-identity.md#7.2; architecture.md#1.12.1 (lines 1144-1174)]
  - [x] Document the data-naming variances the frontend must reconcile (see Dev Notes) so 3.2–3.4 devs are forewarned.

## Dev Notes

### Critical context

- **This is a documentation-only story.** No application code is written. The single deliverable is `docs/bmad_output/planning-artifacts/ux-brief-portal.md`. Do NOT scaffold React components, install `recharts`, or modify `frontend/` source here — that is the job of stories 3.2–3.7. [Source: epics.md#1.6.1; 1-1 story pattern]
- The brief is the agreed design target referenced by all Epic 3 frontend stories. Match the established document structure of `ux-brief-identity.md` exactly (sections 1–4 verbatim in shape, then domain sections, then §7 + References). [Source: ux-brief-identity.md; 1-1 story Task 6]

### RESOLVED conventions conflict — reuse the 1-1 table

The frontend-conventions conflict was already resolved in Story 1.1's brief. Do not re-litigate; reference it. Authoritative = architecture (`src/portals/subscriber/`, `components/ui/` + `components/charts/`, TailwindCSS utility classes only, PascalCase `.tsx` / camelCase hooks). [Source: ux-brief-identity.md#7.2; architecture.md#1.9.1, #1.11.2, #1.12.1 (lines 639, 818-823, 1144-1174)]

### Authoritative route → component map (from architecture §1.12.1)

```
frontend/src/portals/subscriber/   Dashboard.tsx, Balance.tsx, Recharge.tsx, Chatbot.tsx, Profile.tsx, SimActivation.tsx
frontend/src/components/ui/        Button, Card, Badge, Table   (+ NEW: Modal, Input, Select)
frontend/src/components/charts/    UsageRing.tsx (NEW — Recharts wrapper)   ← directory does not exist yet
frontend/src/hooks/                useBalance.ts   (+ NEW: usePlans, useTransactions, useRecharge …)
frontend/src/lib/                  api.ts (Axios + interceptor), auth.ts (JWT role), queryClient.ts (TanStack)
```

[Source: architecture.md:1144-1174; frontend/src/App.tsx:40-49; 1-1 story]

Currently only `Register.tsx` + `SimActivation.tsx` exist under `portals/subscriber/`; `components/charts/` does not exist; `components/ui/` has `Badge`/`Button`/`Card`/`Table` only. [Source: frontend/src/portals/subscriber/, frontend/src/components/ui/index.ts]

### PRD source for the portal flow

- **UJ-2 (Rohan checks his balance and recharges via the subscriber portal)** is the canonical journey this brief serves. [Source: prds/prd-sboai_capstone-2026-06-18/prd.md#UJ-2 (lines 70-71)]
- Relevant FRs the brief must reflect: FR-8 (balance, :204), FR-10 (usage, :224), FR-12 (catalogue, :252), FR-13/14 (recharge + simulated payment, :262/272), FR-15 (receipt, :282), FR-64 (PAN tokenisation, :815). [Source: prd.md §1.5.2 (line 198), §1.5.3 (line 246)]

### Data-naming variances to document in the brief (forewarn 3.2–3.4 devs)

These divergences between the epic AC text and the codebase/schema MUST be called out in the brief so downstream stories don't guess:

1. **`data_gb` (epic) vs `data_limit_mb` (DB).** `plans_plans.data_limit_mb` stores megabytes; usage is metered in MB. The UI shows GB for large values and MB for small (per FR-10 "MB/GB"). Recommend the balance/usage + plans APIs expose both `data_mb` and a derived `data_gb`. [Source: epics.md:1136; service_webapp/db/migrations/V1__baseline_schema.sql:107-123 (data_limit_mb)]
2. **`plan_type` (epic) vs `plan_code`/`plan_name` (DB).** No `plan_type`/`category` column exists on `plans_plans`. The catalogue filter is by validity (28/56/84/all) and sort by price/data — `plan_type` should be derived from `plan_code` (or omitted from the card). [Source: epics.md:1138; V1__baseline_schema.sql:107-123; architecture.md:1205-1206 (synthetic layer uses "category")]
3. **Money is integer paise everywhere** (DB + Valkey + internal API); the UI renders INR with 2 decimals. [Source: architecture.md:1233; 2-3 story]

### Testing standards summary

- This story produces a document; there is no test target. Validation is a checklist review of the brief against ACs 1–6.
- Frontend test tooling for downstream stories: Vitest + React Testing Library (no Cypress for MVP). [Source: architecture.md:977, 1179; frontend/CLAUDE.md §7]

### Project Structure Notes

- Output file goes in **planning-artifacts**: `docs/bmad_output/planning-artifacts/ux-brief-portal.md` (alongside `ux-brief-identity.md`, `architecture.md`, `epics.md`).
- **NEW:** the brief document only. **MODIFIES:** nothing in `frontend/` or `service_webapp/`.
- Variance flagged: `components/charts/` and `UsageRing` are named here but created in Story 3.2; `Modal`/`Input`/`Select` named here but created in Story 3.5.

### References

- [Source: epics.md#1.6.1 Story-3.1 (lines 1118-1142)]
- [Source: architecture.md#1.9.1 (lines 637-645), #1.11.2 (818-823), #1.11.8 (977), #1.12.1 (1144-1174)]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md#UJ-2 (line 70); FR-8 (204), FR-10 (224), FR-12 (252), FR-13 (262), FR-14 (272), FR-15 (282), FR-64 (815)]
- [Source: ux-brief-identity.md (Document Status, §1, §3, §4, §7.2)]
- [Source: frontend/src/App.tsx:40-49; frontend/src/components/ui/index.ts; frontend/CLAUDE.md §2.1, §6.1, §7]
- [Source: 1-1 story (brief format, conflict table), 1-8 story (subscriber role), 1-10 story (token-only payment), 3-2..3-7 stories (downstream consumers)]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (GLM-5.2)

### Debug Log References

### Completion Notes List

- Authored `ux-brief-portal.md` following `ux-brief-identity.md` structure exactly.
- Documented all 5 portal routes (Dashboard, Plans, Recharge, History, Receipt) with component paths and data sources.
- Specified BalanceCard (INR figure from paise, zero-balance warning, IST timestamp) and UsageRing (4 types, circular progress, unlimited label).
- Specified PlanCard catalogue (name, validity badge, quota chips, price, Recharge CTA) with filter/sort controls.
- Specified 3-step Recharge flow (plan select → payment method with tokenisation → confirmation + PDF link).
- Named NEW components: `UsageRing` (charts/), `Modal`/`Input`/`Select` (ui/) — to be created in Stories 3.2 and 3.5.
- Documented conflict-resolution table (architecture layout authoritative; FSD conventions superseded).
- Documented data-naming variances (data_gb vs data_limit_mb; plan_type vs plan_code; paise vs INR).
- No code changes — doc-only story.
- All 6 ACs satisfied; brief committed at `docs/bmad_output/planning-artifacts/ux-brief-portal.md`.

### File List

**New:**
- `docs/bmad_output/planning-artifacts/ux-brief-portal.md`

**Modified:**
- `docs/bmad_output/implementation-artifacts/3-1-ux-brief-balance-usage-recharge-portal-flows.md` (story file: tasks marked, Dev Agent Record filled, Status -> review)
- `docs/bmad_output/implementation-artifacts/sprint-status.yaml` (3-1 updated: in-progress -> review, last_updated -> 2026-06-22)


