# UX Brief: Self-Care Chatbot — CopilotKit Interface & AG-UI Stream Flows

## Document Status

**Type:** Lightweight UX Brief — MVP scope only
**Story:** 5.1 — UX Brief: Chatbot Interface & AG-UI Stream Flows
**Produced:** 2026-06-24
**Authoritative for:** Stories 5.4 (CopilotKit runtime + Support Agent graph), 5.6 (recharge via chatbot), 5.7 (Rating Agent / charge breakdown), 5.9 (plan recommendation + feedback), 5.10 (Conclusion + Notification Agent / session-end)

This document is the agreed design target for all Epic 5 frontend chatbot stories. It defines the chatbot UI layout, AG-UI event handling, tool-call visualisation patterns, `useCopilotReadable` hook contracts, and the CopilotKit runtime URL. It follows the structural pattern of [UX Brief: Subscriber Self-Care Portal](ux-brief-portal.md) and inherits its conventions (TailwindCSS utility classes only, `portals/subscriber/` layout, integer-paise money model, PII hygiene).

It supersedes any conflicting frontend conventions for these flows for the same reasons documented in the portal brief — the Feature-Sliced Design layout and SCSS modules described in `frontend/CLAUDE.md` do **not** apply.

---

## 1. Placement & Component Tree

### 1.1 CopilotChat Component Placement

The `<CopilotChat>` component is embedded as a **bottom-right floating panel** inside the `/subscriber/*` subtree. It is a persistent overlay (not a routed page) so the subscriber can invoke the assistant from any subscriber screen without leaving their current context (balance, plans, history, recharge).

**Visual specification:**

- Floating, bottom-right anchored panel — `position: fixed`, anchored to bottom-right of the viewport
- Sits above portal content — `z-index` above all portal/page content (recommend `z-50`, below modals which remain `z-50+`)
- Collapsed state: a single chat icon button (FAB) in the bottom-right corner
- Expanded state: panel **width 380px**, **max-height 600px**
- Message list is **scrollable** (vertical overflow auto), newest message at the bottom, auto-scroll on new token
- Collapsible via the FAB toggle (click to open, click `×` / chevron to collapse back to FAB)
- Compose input docked at the bottom of the expanded panel (text field + send button)

**Component file:** `frontend/src/portals/subscriber/Chatbot.tsx` (per architecture §1.12.1 frontend tree; reserved slot already documented in the portal brief's layout, line: `Chatbot.tsx # Epic 5 (AG-UI stream)`).

> **Note on naming:** the architecture tree reserves the file `Chatbot.tsx` as the host of `<CopilotChat>`. The React class component from CopilotKit is `<CopilotChat>` (PascalCase); our file is `Chatbot.tsx`. Do not confuse the two.

### 1.2 CopilotKit Wrapper — Portal Root Level

`<CopilotKit>` must wrap the **entire subscriber portal subtree** (wrapping `<Routes>`), not be placed per-page. This is a confirmed architecture decision (ARCH-23). All `useCopilotReadable` hooks and `useCopilotAction` registrations must be called in components that are **children of `<CopilotKit>`**.

`App.tsx` is the role-based router root; the `<CopilotKit>` wrapper is mounted at the subscriber-portal root level so it is in scope for every `/subscriber/*` route. (Today `App.tsx` mounts the subscriber routes directly; Story 5.4 introduces the `<CopilotKit>` wrapper — it does **not** exist yet.)

### 1.3 Component Tree Sketch

```
<SubscriberPortalLayout>
  <CopilotKit runtimeUrl="/api/chat/stream">
    <Routes>
      .../subscriber/dashboard, /plans, /recharge, /history, /receipts/:id ...
    </Routes>

    {/* Hooks are called inside a child of <CopilotKit> */}
    <CopilotChat
      className="sboai-chatbot-panel"
      instructions="You are a billing assistant for SBO-AI prepaid subscribers..."
    />
  </CopilotKit>
</SubscriberPortalLayout>
```

**Key points:**

- `<CopilotChat>` is a sibling of `<Routes>`, both children of `<CopilotKit>` — this lets the chat read React state from any active route via `useCopilotReadable`.
- `className="sboai-chatbot-panel"` carries the bottom-right floating-panel layout (380×600, collapsible) per §1.1.
- `instructions` seeds the Support Agent's system prompt (billing-assistant persona, scope, PII rules).
- The `useCopilotReadable` hooks (§4) are invoked inside `<SubscriberPortalLayout>` or a dedicated `<ChatbotContext>` child of `<CopilotKit>` so the agent receives live balance/plan/session context at render time.

---

## 2. AG-UI Event Handling

The transport is the **AG-UI protocol** — a typed event stream emitted by the CopilotKit runtime over `POST /api/chat/stream`. This **replaces** the prior raw-SSE approach (architecture §1.6.1). CopilotKit's React runtime consumes the typed stream; the frontend maps each AG-UI event type to a UI behaviour.

### 2.1 Event → UI Behaviour Map

| AG-UI Event | UI Behaviour |
|---|---|
| `RunStarted` | Show **typing indicator** (animated dots) in the message list; disable compose input until `RunFinished` |
| `TextMessageStart` | Open a new assistant message bubble (empty) |
| `TextMessageContent` | **Stream token-by-token** into the open assistant bubble (append each delta) |
| `TextMessageEnd` | Finalise the assistant message bubble |
| `ToolCallStart` | Insert a **tool invocation card** (collapsible) showing the tool name and a "running…" state |
| `ToolCallArgs` | (Optional) surface streamed argument fragments inside the card while collapsed |
| `ToolCallEnd` | Resolve the tool card — render the tool-specific result visualisation (§3) based on the returned payload |
| `StateSnapshot` | **Update hook state** — write the snapshot into the values exposed by `useCopilotReadable` hooks (balance, plan, session); these flow back into React state and re-render dependent components |
| `RunFinished` | **Hide typing indicator**; re-enable compose input |

### 2.2 Streaming Rules

- Token streaming (`TextMessageContent`) must feel live: deltas are appended to the open bubble without re-rendering the whole transcript. CopilotKit's runtime handles the delta aggregation; the UI must not buffer the entire message before painting.
- A run may contain **interleaved** text and tool calls (e.g., "Let me look that up…" → `ToolCallStart` → result card → more text). The transcript must preserve this ordering.
- Concurrent/rapid events must be handled idempotently — `StateSnapshot` is a full-state replacement, not an incremental patch; always overwrite, never merge.
- On any error mid-run (runtime returns an error event or the stream closes unexpectedly), hide the typing indicator, surface an inline error in the last assistant bubble ("Something went wrong. Please try again."), and re-enable compose.

---

## 3. Tool-Call Result Visualisation

Each tool the Support Agent can invoke (architecture §1.6.1 tool list) renders a distinct, purpose-built result component inside the transcript when its `ToolCallEnd` payload arrives. The result card replaces the "running…" placeholder from `ToolCallStart`.

### 3.1 `charge_explain` → `<ChargeBreakdownTable>` (collapsible)

**Purpose:** Show the Rating Agent's itemised charge breakdown for a queried CDR/period.

**Collapsed state:** a single summary row — total charge (INR) + event count + a chevron to expand.
**Expanded state:** a table with the columns below.

| Column | Source field | Render |
|---|---|---|
| Event type | `event_type` | e.g., `VOICE`, `DATA`, `SMS`, `ROAMING` (Badge) |
| Duration / Data | `duration` / `data` | Voice/SMS → duration (mm:ss); Data → MB/GB (≥1024 → GB) |
| Rate | `rate` | INR per unit (2 decimals) |
| Charge (paise → INR) | `charge_paise` | `charge_paise / 100`, INR 2 decimals |
| Balance before | `balance_before` | INR 2 decimals |
| Balance after | `balance_after` | INR 2 decimals |

**Money rendering:** all values arrive as integer paise; render INR with `Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })` (consistent with portal brief §4.1).

### 3.2 `recommend_plan` → `<PlanRecommendationCard>` (Accept / Dismiss)

**Purpose:** Present 1–3 recommended plans (FR-32) with rationale and explicit feedback actions.

**Card contents (per recommended plan):**

- Plan name (large, bold) + validity Badge (e.g., "28 days")
- Quota chips (data, voice, SMS) — reuse portal `PlanCard` chip styling
- Price (INR, prominent)
- **Rationale** — the natural-language explanation returned by the recommendation tool (usage signals + hybrid-search match)
- **Accept** button → logs positive feedback to `recommendation_feedback` table (Story 5.9) and offers a recharge deeplink
- **Dismiss** button → logs negative feedback (Story 5.9); card collapses

**Feedback persistence (FR-33):** Accept/Dismiss are not no-ops — they must call the feedback-recording path so the recommendation loop improves (Story 5.9). The Accept action surfaces the same recharge deeplink pattern as `recharge_flow` (§3.4).

### 3.3 `ticket_create` → `<TicketConfirmationBanner>` (with ticket ID)

**Purpose:** Confirm dispute/support-ticket creation (FR-30) with the generated ticket ID.

**Banner contents:**

- Success icon + heading "Support ticket created"
- **Ticket ID** — prominent, copyable (monospace)
- Message: "Our team will review this within **48 hours**."
- (Optional) link to view previously raised tickets (FR-28)

**PII note:** the banner must never echo the full MSISDN or raw dispute text containing PII — reference the subscriber only by masked MSISDN suffix (last 4 digits) where a reference is needed. See §6.

### 3.4 `recharge_flow` → Inline Deeplink Button (NOT an API call)

**Purpose:** Hand the subscriber off to the portal's recharge flow with a pre-selected plan.

**Confirmed architecture decision (arch wins over epics wording, user decision 2026-06-23):** the chatbot does **NOT** call `POST /api/v1/subscriber/recharge` directly. The `recharge_flow` tool returns a **navigable URL**; the chatbot renders an inline button that performs client-side navigation.

**Render:** an inline button — **"Recharge now →"** — which navigates (React Router) to:

```
/subscriber/recharge?plan={plan_id}
```

This deep-links into the existing 3-step recharge wizard (portal brief §6), skipping Step 1 plan-select because `?plan_id=` is present. The wizard then handles payment method + confirmation + simulated payment (FR-14) as in Story 3.5.

> **Rationale:** keeping the actual payment execution inside the established recharge flow preserves tokenisation, receipt generation, and balance-flush wiring. The chatbot is an entry ramp, not a parallel payment path.

### 3.5 Tool Result Components Summary

| Component | File (to be created in Epic 5 stories) | Trigger tool | Story |
|---|---|---|---|
| `ChargeBreakdownTable` | `components/chatbot/ChargeBreakdownTable.tsx` | `charge_explain` | 5.7 |
| `PlanRecommendationCard` | `components/chatbot/PlanRecommendationCard.tsx` | `recommend_plan` | 5.9 |
| `TicketConfirmationBanner` | `components/chatbot/TicketConfirmationBanner.tsx` | `ticket_create` | 5.8 |
| (inline deeplink button) | rendered inline within `Chatbot.tsx` | `recharge_flow` | 5.6 |

A new `components/chatbot/` directory holds these chatbot-specific result components (parallel to `components/ui/`, `components/charts/`). They reuse the shared `components/ui/` primitives (`Button`, `Card`, `Badge`, `Table`) for consistency with the rest of the portal.

---

## 4. `useCopilotReadable` Hooks (ARCH-23)

`useCopilotReadable` exposes React state to the agent at render time so the Support Agent has live subscriber context without an extra round-trip. Three hooks are defined (UX-DR3, ARCH-23). Each is called inside a child of `<CopilotKit>`.

### 4.1 `useSubscriberBalance`

Exposes the subscriber's current wallet balance so the agent can answer balance/quota queries (FR-22) with current data.

```typescript
useCopilotReadable({
  description: "The subscriber's current wallet balance.",
  value: {
    balance_paise: number,   // integer paise
    balance_inr: string,     // formatted "₹NNN.NN"
  },
});
```

**Source:** React Query `useBalance()` hook (Story 3.2) → `GET /api/v1/subscriber/balance`. `balance_inr` is derived client-side via `balance_paise / 100` + `Intl.NumberFormat('en-IN')`. Re-exposed whenever the query refetches / on `StateSnapshot`.

### 4.2 `useActivePlan`

Exposes the subscriber's active plan so the agent can answer plan/expiry queries (FR-23).

```typescript
useCopilotReadable({
  description: "The subscriber's active plan and remaining allowance.",
  value: {
    plan_name: string,
    expiry_date: string,         // ISO 8601 date
    data_remaining_mb: number,   // remaining data in MB
  },
});
```

**Source:** React Query `usePlanDetails()` (Story 3.4) → `GET /api/v1/subscriber/plan` (plan details endpoint). `data_remaining_mb` is the remaining allowance; UI consumers may render GB for large values.

### 4.3 `useChatSession`

Exposes the chat session identifier and turn count so the agent and conclusion logic have continuity (FR-25 conversational context within a single session).

```typescript
useCopilotReadable({
  description: "The current chat session identifier and turn count.",
  value: {
    session_id: string,    // client-generated UUIDv4
    turn_count: number,    // incremented per subscriber message
  },
});
```

**Source:** generated **client-side** — a fresh **UUIDv4** is minted when the chat panel is first opened, stored in React state (lifted to the `<CopilotKit>` child scope so it persists across route changes within the portal). `turn_count` increments on each subscriber-sent message. The `session_id` is the join key for LangFuse traces and the Conclusion Agent's stored learnings (FR-34).

> **TTL note:** the session lives for the browser session / until the 2h `chat_context` TTL (§5) expires or the user closes the panel. A new panel open after close mints a new `session_id`.

---

## 5. Session-End Summary Notification Toast (FR-34, FR-35)

At the end of a chatbot session, the Conclusion Agent stores interaction learnings and the Notification Agent emits a conversation summary. The frontend surfaces this as a **toast notification**.

**Trigger conditions:**

1. `chat_context` **TTL expires** (2 hours of inactivity), **or**
2. The user **clicks close** (`×`) on an expanded panel after a conversation has occurred.

**Toast behaviour:**

- Type: transient toast (top-centre or bottom-centre per portal toast convention), auto-dismiss after ~6s, with a manual close.
- Body copy: **"Chat session ended. {summary}"**
  - `{summary}` = the last assistant message (truncated to ~1 line), **or**
  - If the Conclusion Agent ran (session reached conclusion), `{summary}` = **"Your session has been saved."**
- The toast is purely a UI affordance; the actual summary persistence + Notification Agent A2A call happen server-side (Story 5.10). The frontend decides which `{summary}` string to use based on whether a `RunFinished` with conclusion semantics was received.

> **TTL value:** 2h, per the chat-context expiry documented in epics (epics §1.8.1 AC: "when `chat_context` TTL expires (2h)"). This is a client-side idle timer; reset on any subscriber activity in the panel.

---

## 6. PII Hygiene (ARCH-32)

All chat UI copy and tool-result rendering must follow the project PII hygiene rules (ARCH-32):

- **Never display the full MSISDN** in any chat message, tool card, or confirmation copy. Use only the **last 4 digits** (e.g., "ending in 4242") where a subscriber reference is required.
- **Never** log or echo raw MSISDN, name, address, or card data into the transcript. Tool-result payloads containing PII must be masked before render (the backend should already redact per ARCH-32; the frontend treats any PII-shaped field as untrusted and masks defensively).
- Confirmation banners (§3.3) and recharge deeplinks (§3.4) must not embed PII in the URL query string beyond a non-sensitive `plan_id`.
- No PII in any client-side analytics/telemetry event emitted from the chat panel.

---

## 7. CopilotKit Runtime URL (ARCH-13)

| Item | Value |
|---|---|
| Runtime endpoint | `POST /api/chat/stream` |
| Protocol | AG-UI (typed event stream) — not raw SSE |
| Runtime host | CopilotKit Python SDK wired as a FastAPI router (Story 5.4) |
| Frontend binding | `<CopilotKit runtimeUrl="/api/chat/stream">` |

**Notes:**

- The `/api/chat/stream` path is a FastAPI-served CopilotKit runtime endpoint; the frontend posts the chat request and consumes the AG-UI event stream. CopilotKit's React runtime manages the connection lifecycle.
- All inter-agent A2A calls and the round-trip are traced in LangFuse under a shared `trace_id` (FR-72), correlated with the client-side `session_id` (§4.3).
- This is a confirmed architecture decision (ARCH-13). The brief does not alter the URL; it records it as the binding target for the frontend wrapper.

### CopilotKit Version Guidance

Use `@copilotkit/react-ui` and `@copilotkit/react-core` at **latest stable at implementation time** (as of writing, `^1.x`). The packages are **not yet installed** in the frontend (Story 5.4 adds them). AG-UI is the transport contract — the React runtime consumes typed events; do not hand-roll an SSE parser.

---

## 8. Acceptance Criteria Traceability

| AC | Brief Section | Status |
|---|---|---|
| 1. CopilotChat placement (bottom-right floating, collapsible) | §1.1, §1.3 | Documented |
| 2. Tool-call visualisation (charge table / plan card / ticket banner) | §3.1, §3.2, §3.3 (+ §3.4 deeplink) | Documented |
| 3. Session-end summary toast behaviour | §5 | Documented |
| 4. `useCopilotReadable` hooks (useSubscriberBalance, useActivePlan, useChatSession) | §4 | Documented |
| 5. CopilotKit runtime URL `POST /api/chat/stream` | §7 | Documented |
| 6. Saved as `docs/bmad_output/planning-artifacts/ux-brief-chatbot.md` following portal/identity brief pattern | This file | Done |

---

## 9. Project Structure Notes & Conflict Resolutions

### 9.1 Authoritative Layout (inherited from portal brief)

```
frontend/src/
├── portals/subscriber/
│   └── Chatbot.tsx              # <CopilotChat> host — Story 5.4
├── components/
│   ├── ui/                      # Button, Card, Badge, Table (shared)
│   └── chatbot/                 # NEW (Epic 5): tool-result components
│       ├── ChargeBreakdownTable.tsx   # Story 5.7
│       ├── PlanRecommendationCard.tsx # Story 5.9
│       └── TicketConfirmationBanner.tsx # Story 5.8
├── hooks/
│   ├── useBalance.ts            # Story 3.2 (existing) — source for useSubscriberBalance
│   └── usePlanDetails.ts        # Story 3.4 (existing) — source for useActivePlan
└── App.tsx                      # <CopilotKit> wraps subscriber portal — Story 5.4
```

### 9.2 Conflict Resolutions (this brief)

| Concern | Resolution |
|---|---|
| `recharge_flow` as API call vs deeplink | **Deeplink only** — `recharge_flow` returns a URL `/subscriber/recharge?plan={plan_id}`; chatbot does **not** call `POST /api/v1/subscriber/recharge`. Architecture wins (user decision 2026-06-23). |
| Transport: SSE vs AG-UI | **AG-UI typed event stream** replaces prior raw-SSE approach (architecture §1.6.1). |
| `<CopilotKit>` placement | Portal root level, wrapping `<Routes>` — not per-page (ARCH-23). |
| `session_id` generation | Client-side UUIDv4 on chat open, stored in React state (not server-issued at open). |
| Money model | Integer paise everywhere; INR rendered at `paise/100` with `en-IN` formatting (matches portal brief). |

### 9.3 Data-Naming Variances (carried from portal brief)

- Money: integer paise in tool payloads (`charge_paise`, `balance_before`, `balance_after`); render INR at 2 decimals.
- Data: stored/transmitted in MB; render GB for values ≥ 1024 MB.
- Plan reference: `plan_id` (UUIDv4) for all references and deeplinks; `plan_code` / `plan_name` for display only.

---

## 10. Testing Standards

This story produces a document; there is no test target. Validation is a checklist review of this brief against ACs 1–6 (see §8).

For downstream Epic 5 frontend stories:

- Frontend test tooling: Vitest + React Testing Library (same as Epic 3).
- Test AG-UI event handling by mocking the CopilotKit runtime event stream and asserting UI behaviour per event type (§2.1).
- Test tool-result components in isolation with synthetic tool payloads.
- Accessibility: chat panel must be keyboard-operable (open/close FAB, focus compose input on open, screen-reader roles for message bubbles and tool cards).

---

## References

- [epics.md §1.8.1 Story 5.1](epics.md) — Source epic definition (lines 1484–1506)
- [architecture.md §1.6.1](architecture.md) — Self-Care Chatbot (LangGraph) diagram and CopilotKit details
- [epics.md ARCH-13](epics.md) — CopilotKit runtime URL (`POST /api/chat/stream`)
- [epics.md ARCH-23](epics.md) — CopilotKit frontend + `useCopilotReadable` hooks
- [epics.md ARCH-32](epics.md) — PII hygiene rules
- [epics.md UX-DR3](epics.md) — Chatbot interface design requirement
- [prd.md UJ-3](prds/prd-sboai_capstone-2026-06-18/prd.md) — Canonical chatbot self-service user journey
- [prd.md FR-22–FR-36](prds/prd-sboai_capstone-2026-06-18/prd.md) — Chatbot functional requirements
- [UX Brief: Subscriber Self-Care Portal](ux-brief-portal.md) — Structural pattern + shared conventions (money model, PII, layout)
- [UX Brief: Subscriber Registration & Identity Flows](ux-brief-identity.md) — Canonical brief structure
- Stories 5.4 (runtime + graph), 5.6 (recharge), 5.7 (Rating Agent), 5.8 (dispute/ticket), 5.9 (plan recommendation), 5.10 (Conclusion + Notification Agent) — downstream consumers
