---
baseline_commit: 597ec09b7f4dacee810be9331a16c3dbb43883c2
---

# Story 1.1: UX Brief — Subscriber Registration & Identity Flows

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **product team**,
I want a lightweight UX brief defining screen layouts, component names, and key interactions for subscriber registration, login, and profile flows,
so that frontend stories in this epic have a clear, agreed-upon design target and the developer agent can implement consistent, named components.

## Acceptance Criteria

1. **Given** no UX design document exists and PRD user journey UJ-1 defines the subscriber identity flow, **When** the UX brief is produced, **Then** it documents screen names and routes for: `/register` (multi-step form), `/activate` (order tracker), `/login`, `/profile`, `/profile/kyc`, `/profile/payment-methods`.
2. It specifies the four role-gated route prefixes: `/subscriber/*`, `/ops/*`, `/fraud/*`, `/simulator/*` (UX-DR7).
3. It lists shared UI component names to be created in `frontend/src/components/ui/`: `Button`, `Card`, `Badge`, `Table`, `Modal` (UX-DR8).
4. It describes the registration multi-step form: Step 1 (personal details), Step 2 (TRAI CAF fields), Step 3 (Registration ID display + OTP entry).
5. It specifies the SIM activation order tracker: step indicator showing **Created → KYC Pending → KYC Verified → Activated** states.
6. It defines `PascalCase.tsx` naming convention for all components and `usePascalCase.ts` for hooks (UX-DR8).
7. The brief is committed as a markdown document at `docs/bmad_output/planning-artifacts/ux-brief-identity.md` and is referenced by the downstream frontend stories (1.6, 1.7, 1.8, 1.9, 1.10).

## Tasks / Subtasks

- [x] **Task 1: Author the UX brief document** (AC: #1, #7)
  - [x] Create `docs/bmad_output/planning-artifacts/ux-brief-identity.md`
  - [x] Add a "Document Status" header: lightweight UX brief, MVP scope, supersedes any conflicting frontend conventions for these flows (see Project Structure Notes)
  - [x] Document the route table for the identity flows with screen name, route, portal prefix, and one-line purpose
- [x] **Task 2: Document the route map and role gating** (AC: #1, #2)
  - [x] List subscriber-facing identity routes: `/register`, `/activate`, `/login`, `/profile`, `/profile/kyc`, `/profile/payment-methods`
  - [x] Document the four role-gated prefixes (`/subscriber/*`, `/ops/*`, `/fraud/*`, `/simulator/*`) and the rule: JWT `role` claim selects the accessible subtree; mismatch → redirect to `/login` (UX-DR7, FR-67)
  - [x] Note that `/activate` (SIM order tracker) lives under the `/simulator/*` portal per architecture §1.12.1 (`src/portals/simulator/SimActivation.tsx`), even though it is a subscriber-facing screen — flag this as a known route/portal placement to confirm with downstream story 1.7
- [x] **Task 3: Specify the shared UI component library** (AC: #3, #6)
  - [x] List the five shared components (`Button`, `Card`, `Badge`, `Table`, `Modal`) with their target location `frontend/src/components/ui/`
  - [x] State the styling rule: **TailwindCSS utility classes only**; no per-component CSS files; only `globals.css` permitted (architecture §1.11.2 React rules)
  - [x] State naming: components `PascalCase.tsx`, hooks `usePascalCase.ts`, utility files `camelCase.ts`
  - [x] For `Badge`, specify the three KYC status variants used by Story 1.9: Verified (green), Pending (amber), Rejected (red) — so the component is built once with the right variant API
- [x] **Task 4: Describe the multi-step registration form** (AC: #4)
  - [x] Step 1 — personal details (name, email, alternate mobile number for pre-activation OTP per PRD A-6)
  - [x] Step 2 — TRAI CAF fields (Customer Acquisition Form)
  - [x] Step 3 — display generated Registration ID (`REG-{YYYYMMDD}-{8 hex chars}`) + OTP entry
  - [x] Note the duplicate-MSISDN error surface (HTTP 409 `DUPLICATE_MSISDN`) maps to an inline form error in Step 1/2 (consumed by Story 1.6)
- [x] **Task 5: Specify the SIM activation order tracker** (AC: #5)
  - [x] Four-step indicator: Created → KYC Pending → KYC Verified → Activated
  - [x] Current step highlighted; completed steps show checkmark; polls `GET /api/v1/subscriber/orders/{order_id}/status` every 10s (detail consumed by Story 1.7)
  - [x] On `status = 'ACTIVATED'`, success banner with MSISDN
- [x] **Task 6: Add the Project Structure Notes / conflict callout to the brief** (AC: #7)
  - [x] Document the resolved decision: the architecture's `src/portals/*` + `components/ui/` + TailwindCSS layout is authoritative
  - [x] List the conflicts explicitly so the frontend dev (Story 1.7) knows the existing `frontend/` scaffold must be reorganised

## Dev Notes

### Critical context

- **This is a documentation-only story.** No application code is written. The single deliverable is a markdown UX brief. Do **not** scaffold React components, install packages, or modify `frontend/` source in this story — that is Story 1.7's job. [Source: epics.md#Story-1.1]
- This brief is the agreed design target referenced by all subsequent Epic 1 frontend stories. Its job is to remove ambiguity, not to implement.

### RESOLVED conventions conflict — READ THIS FIRST

There are **two competing sets of frontend conventions** in this repo. The decision for this project is recorded here so downstream stories are unambiguous:

| Concern | **Authoritative (architecture — use this)** | Superseded (`frontend/CLAUDE.md` — do NOT follow for these flows) |
| --- | --- | --- |
| Folder layout | `src/portals/{subscriber,ops,fraud,simulator}/`, `src/components/ui/`, `src/hooks/`, `src/lib/`, `src/types/` | Feature-Sliced Design: `src/features/`, `src/entities/`, `src/shared/`, `src/routes/` |
| Styling | TailwindCSS utility classes only; `globals.css` for resets | `PascalCase.module.scss` SCSS modules |
| Page naming | `SimActivation.tsx`, `Profile.tsx` (plain PascalCase under `portals/<role>/`) | `PascalCasePage.tsx` (e.g. `ProfilePage.tsx`) |
| Hooks | `usePascalCase.ts` (`useBalance.ts`, `useAuth.ts`) | `camelCase.ts` |

The brief MUST state explicitly that the architecture layout wins. [Source: architecture.md#1.9.1, #1.11.2, #1.12.1]

### Authoritative route → component map (from architecture §1.12.1)

```
frontend/src/portals/
  subscriber/   Dashboard.tsx, Balance.tsx, Recharge.tsx, Chatbot.tsx, Profile.tsx
  ops/          PlanStock.tsx, OrderFulfilment.tsx, Forecasts.tsx, Segmentation.tsx
  fraud/        AnomalyFeed.tsx, CaseQueue.tsx
  simulator/    CdrSimulator.tsx, NotificationPortal.tsx, SimActivation.tsx
frontend/src/components/
  ui/           Button, Card, Badge, Table, Modal (TailwindCSS only)
  charts/       Recharts wrappers
  layout/       Navbar, Sidebar, RoleGuard
frontend/src/hooks/   useBalance.ts, useWebSocket.ts, useAuth.ts
frontend/src/lib/     api.ts (Axios + error interceptor), auth.ts (JWT decode/role), queryClient.ts (TanStack Query)
```

[Source: architecture.md#1.12.1-Monorepo-Layout]

### PRD source for the identity flow

- **UJ-1 (Priya activates her SIM after online sign-up)** is the canonical user journey this brief serves. [Source: prds/prd-sboai_capstone-2026-06-18/prd.md#UJ-1, line 67]
- Pre-activation login uses Registration ID + OTP sent to the **alternate mobile number** provided during registration (PRD A-6, FR-4). The registration form Step 1 must therefore collect an alternate mobile number. [Source: prd.md lines 164, 1067]

### State management & real-time (for context, not implementation here)

- Server state: TanStack Query (React Query). No Redux/global store — role-separated dashboards share no state. [Source: architecture.md#1.9.3]
- The order tracker uses 10s polling (not WebSocket) per Story 1.7. [Source: epics.md#Story-1.7]

### Testing standards summary

- This story produces a document; there is no test target. Validation is a human/checklist review of the brief against ACs 1–7.
- Frontend test tooling for downstream stories: Vitest + React Testing Library (no Cypress for MVP). [Source: architecture.md#1.11.8]

### Project Structure Notes

- Output file goes in **planning-artifacts**, not implementation-artifacts: `docs/bmad_output/planning-artifacts/ux-brief-identity.md`. This keeps it alongside `architecture.md` and `epics.md` as a planning reference.
7 — it does **not** perform that reorganisation.
- Variance flagged: `/activate` is a subscriber-facing screen but architecture places `SimActivation.tsx` under `portals/simulator/`. The brief records this as an open placement question for Story 1.7 rather than silently resolving it.

### References

- [Source: epics.md#Story-1.1 (lines 305–321)]
- [Source: architecture.md#1.9.1-Single-SPA-Role-Based-Dashboard-Routing (lines 634–645)]
- [Source: architecture.md#1.11.2-Naming-Conventions (React, lines 818–823)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (frontend tree, lines 1133–1179)]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md#UJ-1 (line 67); A-6 (line 1067); pre-activation OTP (line 164)]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

No blockers. Documentation-only story; all content derived from architecture.md (§1.9.1, §1.11.2, §1.12.1) and prd.md (UJ-1, A-6, FR-4, FR-67).

### Completion Notes List

- Produced `docs/bmad_output/planning-artifacts/ux-brief-identity.md` covering all 6 tasks and 7 ACs.
- Clarified SimActivation dual-placement: architecture monorepo layout shows two files — `portals/subscriber/SimActivation.tsx` (read-only subscriber tracker) and `portals/simulator/SimActivation.tsx` (dev tool). Story file Task 2 referenced only the simulator location; the brief records the correct subscriber location with the open question flagged for Story 1.7.
- Badge component specified with `verified` / `pending` / `rejected` variant API to ensure Story 1.9 can consume it without rework.
- Conflict resolution table explicitly supersedes `frontend/CLAUDE.md` FSD conventions in favour of architecture-defined layout and TailwindCSS styling.

### File List

- docs/bmad_output/planning-artifacts/ux-brief-identity.md (created)
- docs/bmad_output/implementation-artifacts/1-1-ux-brief-subscriber-registration-identity-flows.md (updated — tasks, status, record)
- docs/bmad_output/implementation-artifacts/sprint-status.yaml (updated — story status)

## Change Log

- 2026-06-20: Story 1.1 complete — UX brief authored at `docs/bmad_output/planning-artifacts/ux-brief-identity.md`. All 6 tasks and 7 ACs satisfied. Status set to review.
- 2026-06-20: UX brief amended — added Section 4 (Tailwind Global Theme): font families (Inter/JetBrains Mono), locked type scale (xs→3xl), colour palette (brand/neutral/success/warning/danger tokens), and `tailwind.config.ts` reference snippet. Section numbers 4–6 renumbered to 5–7.
