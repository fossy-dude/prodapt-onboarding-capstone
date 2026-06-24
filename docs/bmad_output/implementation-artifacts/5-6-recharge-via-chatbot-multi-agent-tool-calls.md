---
baseline_commit: 26ccc23
---

# Story 5.6: Recharge via Chatbot & Multi-Agent Tool Calls

Status: review

## Story

As a **subscriber**,
I want to initiate a recharge through the chatbot and be directed to the recharge portal,
so that I can top up my account without leaving the conversation flow.

## Acceptance Criteria

1. **Given** a subscriber asks the chatbot to "recharge" or "top up", **When** the Support Agent detects the recharge intent, **Then** it calls the `list_plans` tool and presents top 3 recommended plans as plan cards in the chat UI. [Source: epics.md:1630; FR-24]
2. **And** the `recharge_flow` tool returns a deeplink URL to `/subscriber/recharge?plan={plan_id}` — the chatbot does NOT call the recharge API directly. The agent responds with the deeplink and a prompt to complete the recharge in the portal. [Source: architecture.md:255 `recharge_flow ──► Link for Recharging in portal`; user decision 2026-06-23]
3. **And** the plan cards are rendered in the chat UI using the `<PlanRecommendationCard>` component (defined in Story 5.1 UX brief) — each card shows: plan name, price, data/voice allowance, and a "Recharge" button that navigates to the deeplink. [Source: ux-brief-chatbot.md; epics.md:1630]
4. **And** if the subscriber has no saved payment method, the agent responds: "You don't have a saved payment method. Please add one at Settings > Payment Methods." [Source: epics.md:1642]
5. **And** the `list_plans` and `recharge_flow` tool calls are traced to LangFuse as tool spans. [Source: epics.md:1636; FR-72]
6. **And** the subscriber's default payment method status is checked via the existing `recharge_payment_methods` table (already in V1 baseline). [Source: V1__baseline_schema.sql; memory: story_conventions_decisions]

## Tasks / Subtasks

- [x] **Task 1: `list_plans` tool** (AC: #1)
  - [x] In `service_webapp/src/agents/support/tools.py` (Story 5.4), add `@tool` function `list_plans(subscriber_id: str, top_n: int = 3) -> list[dict]`.
  - [x] Query: `SELECT id, name, price_paise, data_limit_mb, voice_minutes, sms_count FROM plans_plans WHERE is_active = TRUE ORDER BY price_paise ASC LIMIT %s`. Use `service_webapp/src/db/plans/queries.py` with `get_available_plans(db, limit) -> list[dict]`. [Source: V1__baseline_schema.sql plans_plans table]
  - [x] Returns: `[{"plan_id": str, "name": str, "price_paise": int, "price_inr": "₹X.XX", "data_limit_mb": int, "voice_minutes": int, "sms_count": int}]`
  - [x] Recommendation: show cheapest 3 by default. If Story 5.9 (plan recommendation tool) is already merged, delegate to `recommend_plan()` instead.

- [x] **Task 2: `recharge_flow` tool** (AC: #2, #4, #5)
  - [x] In `service_webapp/src/agents/support/tools.py`, add `@tool` function `recharge_flow(subscriber_id: str, plan_id: str) -> dict`.
  - [x] Check for saved payment method: query `recharge_payment_methods WHERE subscriber_id = %s AND is_active = TRUE LIMIT 1`. [Source: V1__baseline_schema.sql; memory: story_conventions_decisions — canonical table = recharge_payment_methods]
  - [x] If no payment method found: return `{"status": "no_payment_method", "message": "You don't have a saved payment method. Please add one at Settings > Payment Methods."}`.
  - [x] If payment method exists: return `{"status": "deeplink", "url": f"/subscriber/recharge?plan={plan_id}", "message": f"To complete your recharge, click here: /subscriber/recharge?plan={plan_id}. Your saved payment method will be pre-selected."}`. [Source: architecture.md:255; user decision 2026-06-23]
  - [x] The agent presents the deeplink URL as a clickable button in the chat — NOT an API call from the agent. This is intentional (arch wins over epics wording).

- [x] **Task 3: LangFuse tool span tracing** (AC: #5)
  - [x] Wrap `list_plans` and `recharge_flow` tool calls with LangFuse span: `name="tool_call", input={"tool": "list_plans", "args": {...}}, output={"plans": [...]}`. Use the existing tracing pattern from Story 5.4. [Source: epics.md:1636; FR-72]

- [x] **Task 4: Frontend plan card rendering** (AC: #3)
  - [x] Create `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx`.
  - [x] Props: `{ plan_id: string, name: string, price_inr: string, data_limit_mb: number, voice_minutes: number, recharge_url: string }`.
  - [x] Renders: plan name, price badge, data/voice allowance, "Recharge →" button (navigates via `window.location.href = recharge_url` or React Router `<Link to={recharge_url}>`).
  - [x] CopilotKit renders tool results as custom components via `useCopilotAction` — register `list_plans` result rendering:
    ```tsx
    useCopilotAction({
      name: "list_plans",
      render: ({ result }) => (
        <div className="plan-cards">
          {result.plans.map(plan => <PlanRecommendationCard key={plan.plan_id} {...plan} recharge_url={`/subscriber/recharge?plan=${plan.plan_id}`} />)}
        </div>
      )
    });
    ```
    [Source: CopilotKit docs — useCopilotAction for tool result rendering; ux-brief-chatbot.md]

- [x] **Task 5: Tests** (AC: #1, #2, #4)
  - [x] `service_webapp/tests/unit/test_recharge_tools.py`: mock DB.
    - `list_plans` returns top 3 cheapest active plans.
    - `recharge_flow` with no payment method → no_payment_method status.
    - `recharge_flow` with saved payment method → deeplink URL with correct plan_id.
  - [x] No integration test needed for this story — DB queries follow same patterns as existing tool tests.

## Dev Notes

### Architecture decision: deeplink, NOT direct API call

Epics §1.8.6 AC says the chatbot calls `initiate_recharge` tool which POSTs to `/api/v1/subscriber/recharge`. **This was overridden** by the architecture diagram (§1.6.1): `Tool: recharge_flow ──► Link for Recharging in portal`. The implementation MUST return a deeplink, not make a payment API call from the chatbot. Rationale: payment flows require UI confirmation, payment selection UX, and PCI-DSS compliance — these are handled by the portal's existing recharge flow (Epic 3 Story 3.5), not the chatbot. [Source: architecture.md §1.6.1; user decision 2026-06-23]

### recharge_payment_methods — canonical table name

Epics sometimes say `payment_methods`. Canonical = `recharge_payment_methods` per memory: story_conventions_decisions. The V1 migration confirms this name. [Source: memory: story_conventions_decisions; V1__baseline_schema.sql]

### No new migration

All tables used (`plans_plans`, `recharge_payment_methods`) are in V1 baseline. No Flyway migration needed for Story 5.6. [Source: V1__baseline_schema.sql]

### useCopilotAction for tool result rendering

CopilotKit's `useCopilotAction` hook lets the frontend register custom renderers for specific tool results. When the agent calls `list_plans`, CopilotKit streams a `ToolCallEnd` AG-UI event; the `useCopilotAction` renderer intercepts it and renders `<PlanRecommendationCard>` components. This is the intended CopilotKit pattern — do NOT try to parse the agent's text response to extract plan data. [Source: architecture.md §1.6.1 Frontend — CopilotKit]

### Payment method check — MSISDN vs subscriber_id

`recharge_payment_methods` is keyed by `subscriber_id` (UUID). The tool receives `subscriber_id` from the agent state (populated from JWT claims). Do NOT use MSISDN as the key — use the UUID. [Source: V1__baseline_schema.sql recharge_payment_methods schema]

### Project Structure Notes

- Modified: `service_webapp/src/agents/support/graph.py` (add list_plans + recharge_flow tools)
- New: `service_webapp/src/db/plans/queries.py` (get_available_plans) — if not already created by Story 4.4
- New: `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx`
- No migration, no new deps (already added in 5.3/5.4).

### References

- [Source: epics.md §1.8.6 — Story 5.6 acceptance criteria]
- [Source: architecture.md §1.6.1 — agent diagram: recharge_flow → Link for Recharging in portal]
- [Source: architecture.md:FR-24 — Recharge assistance via chatbot]
- [Source: architecture.md:FR-72 — LangFuse tool span tracing]
- [Source: V1__baseline_schema.sql — plans_plans, recharge_payment_methods tables]
- [Source: memory: story_conventions_decisions — canonical table recharge_payment_methods]
- [Source: ux-brief-chatbot.md — PlanRecommendationCard component spec]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

No issues encountered during implementation.

### Completion Notes List

Story 5.6 implementation completed successfully:

1. **Task 1 - list_plans tool**: Implemented in `service_webapp/src/agents/support/tools.py` as a LangChain `@tool` function. Queries `plans_plans` table via `get_available_plans()` from `service_webapp/src/db/plans/queries.py`. Returns top 3 cheapest active plans with formatted price strings. Handles unlimited quotas (NULL values) correctly.

2. **Task 2 - recharge_flow tool**: Implemented in `service_webapp/src/agents/support/tools.py` as a LangChain `@tool` function. Checks for saved payment methods in `recharge_payment_methods` table. Returns deeplink URL when payment method exists, or error message prompting user to add payment method when none found. Architecture decision: returns deeplink, not direct API call (per architecture §1.6.1).

3. **Task 3 - LangFuse tracing**: Added `tool_call` span tracing for both `list_plans` and `recharge_flow` tools. Wraps tool execution with LangFuse observation context manager, capturing input args and output results. Follows same pattern as Story 5.4 agent tracing.

4. **Task 4 - Frontend components**: Created `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` following project standards (PascalCase, no default exports, Tailwind CSS). Integrated with Chatbot component via `useCopilotAction` hook to render plan cards when `list_plans` tool is called. Cards display plan name, price badge, quotas, and "Recharge →" button.

5. **Task 5 - Tests**: Created `service_webapp/tests/unit/test_recharge_tools.py` with 12 comprehensive tests covering all ACs. Tests verify:
   - `list_plans` returns top 3 cheapest plans
   - `list_plans` respects `top_n` parameter
   - `list_plans` handles unlimited quotas (NULL values)
   - `recharge_flow` returns deeplink when payment method exists
   - `recharge_flow` returns error when no payment method
   - Proper error handling when DB not initialized
   - All 12 tests passing

All acceptance criteria satisfied:
- AC #1: `list_plans` returns top 3 cheapest plans as plan cards ✓
- AC #2: `recharge_flow` returns deeplink URL to recharge portal ✓
- AC #3: Plan cards rendered via `<PlanRecommendationCard>` component ✓
- AC #4: No payment method error message displayed ✓
- AC #5: Tool calls traced to LangFuse ✓
- AC #6: Payment method status checked via `recharge_payment_methods` table ✓

### File List

#### Modified Files
- `service_webapp/src/agents/support/tools.py` - Added `list_plans` and `recharge_flow` tools with LangFuse tracing
- `service_webapp/src/db/plans/queries.py` - Added `get_payment_method_for_subscriber()` function
- `frontend/src/portals/subscriber/Chatbot.tsx` - Added `useCopilotAction` registration for `list_plans` rendering
- `docs/bmad_output/implementation-artifacts/5-6-recharge-via-chatbot-multi-agent-tool-calls.md` - Story status updated to "review"

#### New Files
- `service_webapp/tests/unit/test_recharge_tools.py` - Unit tests for recharge tools (12 tests, all passing)
- `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` - Plan card component for chat UI

#### No Changes Required
- No database migration needed (uses existing V1 tables)
- No new dependencies added
- No integration tests needed (follows existing tool patterns)
