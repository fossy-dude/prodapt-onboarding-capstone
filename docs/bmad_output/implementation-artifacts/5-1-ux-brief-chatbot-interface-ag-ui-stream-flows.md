---
baseline_commit: 3c5d585
---

# Story 5.1: UX Brief — Chatbot Interface & AG-UI Stream Flows

Status: ready-for-dev

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

- [ ] **Task 1: Create UX brief document** (AC: #1–#6)
  - [ ] Create `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md`.
  - [ ] Document CopilotChat component placement: `<CopilotChat>` embedded in `/subscriber/Chatbot.tsx` as a bottom-right floating panel (z-index above portal content), collapsible via a chat icon button. Panel width 380px, max-height 600px, scrollable message list. [Source: architecture.md:264–269]
  - [ ] Define AG-UI event handling: `RunStarted` → show typing indicator; `TextMessageContent` → stream token-by-token; `ToolCallStart/Args/End` → show tool invocation card (collapsible); `StateSnapshot` → update hook state; `RunFinished` → hide typing indicator. [Source: architecture.md:248–252]
  - [ ] Specify tool-call visualisation patterns:
    - `charge_explain` result → collapsible `<ChargeBreakdownTable>` (columns: event_type, duration/data, rate, charge_paise, balance_before/after)
    - `recommend_plan` result → `<PlanRecommendationCard>` with plan name, price, rationale, Accept/Dismiss buttons
    - `ticket_create` result → `<TicketConfirmationBanner>` with ticket ID and "review within 48h" message
    - `recharge_flow` result → inline deeplink button "Recharge now →" navigating to `/subscriber/recharge?plan={plan_id}`
  - [ ] Specify session-end toast: when `chat_context` TTL expires (2h) or user clicks close, show toast: "Chat session ended. {summary}" — summary is the last message or "Your session has been saved." if Conclusion Agent ran. [Source: epics.md:1503]
  - [ ] Define `useCopilotReadable` hooks:
    - `useSubscriberBalance`: exposes `{ balance_paise: number, balance_inr: string }` — sourced from React Query `useBalance()` hook (already in Story 3.2)
    - `useActivePlan`: exposes `{ plan_name: string, expiry_date: string, data_remaining_mb: number }` — sourced from React Query `usePlanDetails()`
    - `useChatSession`: exposes `{ session_id: string, turn_count: number }` — generated client-side UUIDv4 on chat open, stored in React state
  - [ ] Confirm runtime URL: `POST /api/chat/stream` — CopilotKit runtime FastAPI endpoint, streamed SSE/AG-UI events. [Source: architecture.md:ARCH-13]
  - [ ] Include component tree sketch:
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
  - [ ] Add PII note: chat messages must never display full MSISDN — use last 4 digits only in any confirmation copy. [Source: architecture.md:ARCH-32]

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

### Completion Notes List

### File List
