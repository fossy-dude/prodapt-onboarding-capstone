---
baseline_commit: 3c5d585
---

# Story 5.1: UX Brief — Chatbot Interface & AG-UI Stream Flows

Status: review

## Story

As a **product team**,
I want a lightweight UX brief defining the chatbot UI layout, AG-UI event handling, and tool-call visualisation patterns,
so that chatbot frontend stories have a clear design target.

## Acceptance Criteria

1. **Given** PRD user journey UJ-3 defines the chatbot self-service flow, **When** the UX brief is produced, **Then** it documents the CopilotChat component placement: embedded bottom-right panel in the `/subscriber/*` layout, collapsible. [Source: epics.md:1498–1500]
2. **And** it defines how tool-call results are visualised: charge breakdown → collapsible table, plan recommendation → plan card with Accept/Dismiss buttons, ticket creation → confirmation banner with ticket ID. [Source: epics.md:1500–1502]
3. **And** it specifies the session-end summary notification toast behaviour. [Source: epics.md:1503]
4. **And** it defines `useCopilotReadable` hook names: `useSubscriberBalance`, `useActivePlan`, `useChatSession`. [Source: epics.md:1504; architecture.md:ARCH-23]
5. **And** it confirms the CopilotKit runtime URL: `POST /api/chat/stream`. [Source: epics.md:1506; architecture.md:ARCH-13]
6. **And** the brief is saved as `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md` following the pattern of `ux-brief-identity.md` and `ux-brief-portal.md`. [Source: planning-artifacts/ existing pattern]

## Tasks / Subtasks

- [x] **Task 1: Create UX brief document** (AC: #1–#6)
  - [x] Create `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md`.
  - [x] Document CopilotChat component placement: `<CopilotChat>` embedded in `/subscriber/Chatbot.tsx` as a bottom-right floating panel (z-index above portal content), collapsible via a chat icon button. Panel width 380px, max-height 600px, scrollable message list. [Source: architecture.md:264–269]
  - [x] Define AG-UI event handling: `RunStarted` → show typing indicator; `TextMessageContent` → stream token-by-token; `ToolCallStart/Args/End` → show tool invocation card (collapsible); `StateSnapshot` → update hook state; `RunFinished` → hide typing indicator. [Source: architecture.md:248–252]
  - [x] Specify tool-call visualisation patterns:
    - `charge_explain` result → collapsible `<ChargeBreakdownTable>` (columns: event_type, duration/data, rate, charge_paise, balance_before/after)
    - `recommend_plan` result → `<PlanRecommendationCard>` with plan name, price, rationale, Accept/Dismiss buttons
    - `ticket_create` result → `<TicketConfirmationBanner>` with ticket ID and "review within 48h" message
    - `recharge_flow` result → inline deeplink button "Recharge now →" navigating to `/subscriber/recharge?plan={plan_id}`
  - [x] Specify session-end toast: when `chat_context` TTL expires (2h) or user clicks close, show toast: "Chat session ended. {summary}" — summary is the last message or "Your session has been saved." if Conclusion Agent ran. [Source: epics.md:1503]
  - [x] Define `useCopilotReadable` hooks:
    - `useSubscriberBalance`: exposes `{ balance_paise: number, balance_inr: string }` — sourced from React Query `useBalance()` hook (already in Story 3.2)
    - `useActivePlan`: exposes `{ plan_name: string, expiry_date: string, data_remaining_mb: number }` — sourced from React Query `usePlanDetails()`
    - `useChatSession`: exposes `{ session_id: string, turn_count: number }` — generated client-side UUIDv4 on chat open, stored in React state
  - [x] Confirm runtime URL: `POST /api/chat/stream` — CopilotKit runtime FastAPI endpoint, streamed SSE/AG-UI events. [Source: architecture.md:ARCH-13]
  - [x] Include component tree sketch:
    ```
    <SubscriberPortalLayout>
      <CopilotKit runtimeUrl="/api/chat/stream">
        <Routes>...</Routes>
        <CopilotChat
          className="sboai-chatbot-panel"
          instructions="You are a billing assistant..."
        />
      </CopilotKit>
    </SubscriberPortalLayout>
    ```
  - [x] Add PII note: chat messages must never display full MSISDN — use last 4 digits only in any confirmation copy. [Source: architecture.md:ARCH-32]

## Dev Notes

### Output only — no application code

Story 5.1 produces a planning document, NOT application code. The dev agent task is to:
1. Synthesise architecture.md §1.6.1, epics.md §1.8.1, and ux-brief-portal.md patterns into `ux-brief-chatbot.md`.
2. Resolve any ambiguities between epics AC and architecture diagram.
3. Produce the brief so that Stories 5.4–5.10 frontend devs have a design target.

### CopilotKit version guidance

Use `@copilotkit/react-ui` and `@copilotkit/react-core` latest stable at implementation time. As of writing, this is `^1.x`. The AG-UI protocol (typed event stream) is the transport — not raw SSE. [Source: architecture.md:100–101; §1.6.1]

### recharge_flow is a deeplink, not an API call

Architecture diagram shows `Tool: recharge_flow ──► Link for Recharging in portal`. The chatbot does NOT call `POST /api/v1/subscriber/recharge` directly — it returns a navigable URL. This is a confirmed architecture decision (arch wins over epics wording). UX brief must reflect this. [Source: architecture.md:255; user decision 2026-06-23]

### Existing portal structure

- Frontend lives at `frontend/src/portals/subscriber/` per Story 1.7 reorganisation.
- `<CopilotKit>` wrapper must be placed at portal root level (wrapping `<Routes>`), not per-page.
- `useCopilotReadable` hooks must be called inside a component that is a child of `<CopilotKit>`.

### Project Structure Notes

- UX brief output: `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md`
- Story file: `docs/bmad_output/implementation-artifacts/5-1-ux-brief-chatbot-interface-ag-ui-stream-flows.md`
- Pattern source: `docs/bmad_output/planning-artifacts/ux-brief-portal.md`

### References

- [Source: architecture.md §1.6.1 — Self-Care Chatbot (LangGraph) diagram and CopilotKit details]
- [Source: architecture.md:ARCH-13 — CopilotKit runtime URL]
- [Source: architecture.md:ARCH-23 — useCopilotReadable hooks]
- [Source: architecture.md:ARCH-32 — PII hygiene rules]
- [Source: epics.md §1.8.1 — Story 5.1 acceptance criteria]
- [Source: docs/bmad_output/planning-artifacts/ux-brief-portal.md — structural pattern]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

(none — output-only story, no application code executed)

### Completion Notes List

- Produced `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md`, the design target for Epic 5 chatbot frontend stories (5.4, 5.6, 5.7, 5.8, 5.9, 5.10).
- Synthesised architecture.md §1.6.1 (Self-Care Chatbot diagram + CopilotKit details), epics.md §1.8.1 (Story 5.1 ACs), and the ux-brief-portal.md structural pattern + shared conventions (TailwindCSS, portals/subscriber layout, integer-paise money model, PII hygiene).
- Documented all 6 ACs: (1) CopilotChat bottom-right floating panel placement (380px x max 600px, scrollable, collapsible via FAB, z-index above portal content), `<CopilotKit>` wrapping subscriber portal at root level; (2) AG-UI event handling map (RunStarted/TextMessageContent/ToolCall*/StateSnapshot/RunFinished); (3) tool-call visualisations — charge_explain -> collapsible ChargeBreakdownTable (event_type, duration/data, rate, charge_paise, balance_before/after), recommend_plan -> PlanRecommendationCard (Accept/Dismiss), ticket_create -> TicketConfirmationBanner (ticket ID + 48h), recharge_flow -> inline "Recharge now ->" deeplink; (4) useCopilotReadable hooks useSubscriberBalance/useActivePlan/useChatSession with exact value contracts and React Query sources; (5) runtime URL POST /api/chat/stream (AG-UI, not raw SSE); (6) session-end summary toast behaviour (2h TTL or close, "Chat session ended. {summary}", "Your session has been saved." if Conclusion Agent ran).
- Resolved conflicts per Dev Notes: recharge_flow is a deeplink to /subscriber/recharge?plan={plan_id} (arch wins over epics wording, user decision 2026-06-23); AG-UI typed event stream replaces prior SSE; session_id is client-generated UUIDv4 on chat open.
- Added PII hygiene section (ARCH-32): never display full MSISDN, last-4 only; no raw PII in transcript/URLs/telemetry.
- Brief §8 provides AC traceability table; §10 documents downstream Vitest + RTL testing standards. Validation = checklist review (no test target for this doc-only story).
- Verified current frontend state: CopilotKit packages not yet installed and Chatbot.tsx not yet created — confirming this brief is the forward-looking design target for Story 5.4.

### File List

- `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md` (NEW — the UX brief, the sole deliverable)
- `docs/bmad_output/implementation-artifacts/5-1-ux-brief-chatbot-interface-ag-ui-stream-flows.md` (MODIFIED — tasks checked, Dev Agent Record/File List/Change Log populated, Status -> review)
- `docs/bmad_output/implementation-artifacts/sprint-status.yaml` (MODIFIED — Story 5.1 status -> review, last_updated)

### Change Log

- 2026-06-24: Story 5.1 implemented — produced ux-brief-chatbot.md design target covering CopilotChat placement, AG-UI event handling, tool-call visualisations, useCopilotReadable hooks, session-end toast, runtime URL, and PII hygiene. Story moved ready-for-dev -> in-progress -> review.
