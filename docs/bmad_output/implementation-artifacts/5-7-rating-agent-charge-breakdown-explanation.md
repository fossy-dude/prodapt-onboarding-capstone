---
baseline_commit: 3c5d585
---

# Story 5.7: Rating Agent — Charge Breakdown Explanation

Status: ready-for-dev

## Story

As a **subscriber**,
I want to ask the chatbot why I was charged a specific amount and get a detailed breakdown,
so that I can understand my bill and dispute it if needed.

## Acceptance Criteria

1. **Given** a subscriber asks "why was I charged X on [date]?", **When** the Support Agent identifies the charge breakdown intent, **Then** it invokes the Rating Agent (A2A) via LangGraph node with the CDR reference and `subscriber_id`. [Source: epics.md:1660; FR-29]
2. **And** the Rating Agent queries `billing_audit_log` for the CDR, fetches the plan's rate for that event type (voice/data/SMS), and returns: `cdr_id`, `event_type`, `duration_or_data`, `rate_per_unit`, `charge_paise`, `balance_before`, `balance_after`. [Source: epics.md:1662]
3. **And** the Support Agent presents the breakdown as a collapsible table in the chat UI (rendered via `useCopilotAction` for `charge_explain` tool, as defined in Story 5.1 UX brief). [Source: epics.md:1664; ux-brief-chatbot.md]
4. **And** both the Support Agent → Rating Agent call and Rating Agent response are traced as child spans in LangFuse with matching `trace_id`. [Source: epics.md:1666; FR-72]

## Tasks / Subtasks

- [ ] **Task 1: Rating Agent LangGraph graph** (AC: #1, #2, #4)
  - [ ] Create `service_webapp/src/agents/rating/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/rating/graph.py`.
  - [ ] Define `RatingAgentState(TypedDict)`: `subscriber_id: str`, `cdr_reference: str`, `result: ChargeBreakdown | None`, `trace_id: str`.
  - [ ] Dataclass `ChargeBreakdown`: `cdr_id: str, event_type: str, duration_or_data: str, rate_per_unit: int, charge_paise: int, balance_before: int, balance_after: int`.
  - [ ] Node `fetch_breakdown(state: RatingAgentState) -> RatingAgentState`:
    - Query `billing_audit_log` via `service_webapp/src/db/billing/queries.py`:
      ```sql
      SELECT a.cdr_id, a.event_type, a.event_detail, a.charge_paise,
             a.balance_before, a.balance_after, p.voice_rate_paise, p.data_rate_paise_mb
      FROM billing_audit_log a
      JOIN plans_subscriptions ps ON ps.subscriber_id = a.subscriber_id AND ps.status = 'active'
      JOIN plans_plans p ON p.id = ps.plan_id
      WHERE a.subscriber_id = %(subscriber_id)s AND a.cdr_id = %(cdr_reference)s
      LIMIT 1
      ```
    - Parse `event_type` to pick correct `rate_per_unit`: voice → `voice_rate_paise` per minute, data → `data_rate_paise_mb` per MB, SMS → `sms_rate_paise` (from plan config).
    - Compute `duration_or_data`: for voice → `f"{event_detail.get('duration_seconds', 0) // 60}m {event_detail.get('duration_seconds', 0) % 60}s"`, for data → `f"{event_detail.get('volume_mb', 0):.2f}MB"`.
    - Set `state.result = ChargeBreakdown(...)`.
  - [ ] Build graph: single node `fetch_breakdown` → `END`. Compile with `graph.compile()`.
  - [ ] The Rating Agent is a single-node deterministic graph — no LLM call needed. It fetches and formats data from the DB. [Source: epics.md:1662]

- [ ] **Task 2: `charge_explain` tool in Support Agent** (AC: #1, #4)
  - [ ] In `service_webapp/src/agents/support/graph.py`, add `@tool` function `charge_explain(subscriber_id: str, cdr_reference: str) -> dict`.
  - [ ] Invoke Rating Agent: `result = await rating_graph.ainvoke({"subscriber_id": subscriber_id, "cdr_reference": cdr_reference, "trace_id": current_trace_id})`.
  - [ ] The A2A call is a direct LangGraph graph invocation (not HTTP) — same process, same event loop. [Source: architecture.md §1.6.1; A2A protocol: LangGraph inter-node calls]
  - [ ] Return `result["result"]` as dict (via `dataclasses.asdict`).
  - [ ] LangFuse: wrap in child span `name="a2a_rating_agent"`, with `parent_observation_id` from the parent Support Agent trace. Use LangFuse SDK's `trace.span(name="a2a_rating_agent", ...)` so Rating Agent span is nested under Support Agent trace. [Source: epics.md:1666; FR-72]

- [ ] **Task 3: billing_audit_log query** (AC: #2)
  - [ ] Add `get_charge_breakdown(db, subscriber_id: str, cdr_reference: str) -> dict | None` to `service_webapp/src/db/billing/queries.py`.
  - [ ] The query joins `billing_audit_log` + `plans_subscriptions` + `plans_plans`. If CDR not found → return `None`; agent responds "I couldn't find a charge with that reference. Could you provide the date instead?"
  - [ ] NOTE: `billing_audit_log` is append-only (ARCH per V2 migration). Query with `sboai_readonly` role-capable connection. [Source: V2__modified_at_trigger.sql — append-only pattern; architecture.md CQRS]

- [ ] **Task 4: Frontend charge breakdown rendering** (AC: #3)
  - [ ] Create `frontend/src/portals/subscriber/components/ChargeBreakdownTable.tsx`.
  - [ ] Props: `{ cdr_id: string, event_type: string, duration_or_data: string, rate_per_unit: number, charge_paise: number, balance_before: number, balance_after: number }`.
  - [ ] Renders collapsible table (use existing Tailwind disclosure pattern from portal). Shows: Event Type, Duration/Data, Rate, Charge (₹), Balance Before (₹), Balance After (₹). [Source: ux-brief-chatbot.md]
  - [ ] Register `charge_explain` action renderer:
    ```tsx
    useCopilotAction({
      name: "charge_explain",
      render: ({ result }) => result ? <ChargeBreakdownTable {...result} /> : null
    });
    ```

- [ ] **Task 5: Tests** (AC: #1–#4)
  - [ ] `service_webapp/tests/unit/test_rating_agent.py`: mock DB with known audit log row. Invoke `rating_graph.ainvoke(...)` → verify `ChargeBreakdown` fields correct; CDR not found → result is None; voice/data/SMS types compute correct duration_or_data string.
  - [ ] `service_webapp/tests/unit/test_charge_explain_tool.py`: mock Rating Agent graph. Verify `charge_explain` tool invokes graph, returns dict; LangFuse child span called.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres with V1 migration seeded with one billing_audit_log row. Verify full breakdown query returns correct fields.

## Dev Notes

### A2A = same-process LangGraph invocation

"A2A" in this architecture means the Support Agent calls the Rating Agent's compiled LangGraph graph via `await rating_graph.ainvoke(...)` — NOT via HTTP or Kafka. Both agents run in the same `service_webapp` FastAPI process. The Rating Agent is imported as a module singleton. [Source: architecture.md §1.6.1 — A2A protocol: LangGraph inter-node calls with shared state graph]

### Rating Agent is deterministic — no LLM

The Rating Agent fetches structured billing data from Postgres. No LLM call is made in Story 5.7. The LLM (in the Support Agent) uses the Rating Agent's structured output to explain the breakdown in natural language to the subscriber. This separation keeps the expensive LLM call on the explanation side, not the data fetching side.

### billing_audit_log schema

`billing_audit_log` (UUIDv7) exists in V1 baseline. Columns include: `id`, `cdr_id` (reference to `billing_cdr_events`), `subscriber_id`, `event_type`, `event_detail` (JSONB), `charge_paise`, `balance_before`, `balance_after`, `created_at`. Verify actual column names from `V1__baseline_schema.sql` before writing queries. [Source: V1__baseline_schema.sql billing_audit_log]

### plans_plans rate columns

Verify rate column names in `plans_plans` from V1 baseline: likely `voice_rate_paise_per_minute`, `data_rate_paise_per_mb`, `sms_rate_paise`. If columns differ, adapt the query. Do NOT assume column names — read V1 migration first. [Source: V1__baseline_schema.sql plans_plans]

### LangFuse child spans for A2A

LangFuse supports nested spans via `parent_observation_id`. When the Support Agent starts a trace, pass the trace ID into `charge_explain`. In the Rating Agent invocation, create a child span on the same trace. The `trace_id` field in `RatingAgentState` carries this through. [Source: architecture.md:FR-72; LangFuse SDK docs]

### No new migration

`billing_audit_log`, `plans_plans`, `plans_subscriptions` all exist in V1 baseline. No Flyway migration needed for Story 5.7. [Source: V1__baseline_schema.sql]

### Project Structure Notes

- New: `service_webapp/src/agents/rating/graph.py`
- New: `service_webapp/src/db/billing/queries.py` — add `get_charge_breakdown` (if not already present from earlier stories)
- New: `frontend/src/portals/subscriber/components/ChargeBreakdownTable.tsx`
- Modified: `service_webapp/src/agents/support/graph.py` (add charge_explain tool, wire rating_graph singleton)
- No migration, no new Python deps (langgraph already added in 5.4).

### References

- [Source: epics.md §1.8.7 — Story 5.7 acceptance criteria]
- [Source: architecture.md §1.6.1 — agent diagram: charge_explain → Rating Agent]
- [Source: architecture.md:FR-29 — Rating Agent (charge breakdown explanation)]
- [Source: architecture.md:FR-72 — LangFuse agent tracing with child spans]
- [Source: V1__baseline_schema.sql — billing_audit_log, plans_plans, plans_subscriptions]
- [Source: ux-brief-chatbot.md — ChargeBreakdownTable collapsible rendering]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
