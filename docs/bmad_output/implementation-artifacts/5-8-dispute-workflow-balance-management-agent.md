---
baseline_commit: 3c5d585
---

# Story 5.8: Dispute Workflow & Balance Management Agent

Status: ready-for-dev

## Story

As a **subscriber**,
I want to raise a billing dispute via the chatbot and have a support ticket auto-created with pre-filled details,
so that I don't have to repeat information and I have a ticket ID to track my case.

## Acceptance Criteria

1. **Given** a subscriber says "I want to dispute a charge" or "this charge is wrong", **When** the Support Agent detects the dispute intent, **Then** it asks for the CDR reference (or date) to identify the charge, fetches the breakdown via the Rating Agent (Story 5.7), and presents it for confirmation. [Source: epics.md:1684; FR-30]
2. **And** on subscriber confirmation, it calls `POST /api/v1/support/tickets` with pre-filled: `subscriber_id`, `cdr_reference`, `charge_paise`, `dispute_reason = "subscriber_initiated"`, `status = OPEN`. [Source: epics.md:1686]
3. **And** the chatbot responds: "Ticket #{ticket_id} has been created. Our team will review it within 48 hours." [Source: epics.md:1688]
4. **And** `GET /api/v1/support/tickets` lists the subscriber's open tickets with `status` and `created_at`. [Source: epics.md:1690; FR-28]
5. **Given** a subscriber asks "what's my wallet balance?" in chat, **When** the Support Agent detects a wallet query, **Then** it invokes the Balance Management Agent (A2A) which reads `balance:{msisdn}` from Valkey and returns the current balance in paise. [Source: epics.md:1694; FR-31]
6. **And** the A2A call (Balance Management Agent) is traced as a child span in LangFuse. [Source: epics.md:1698; FR-72]
7. **And** the `support_tickets` table (already in V1 baseline) is used — NO new migration required. [Source: V1__baseline_schema.sql:359–376; user decision: V1 = full baseline]

## Tasks / Subtasks

- [ ] **Task 1: Support tickets FastAPI router** (AC: #2, #3, #4)
  - [ ] Create `service_webapp/src/routers/support.py`.
  - [ ] `POST /api/v1/support/tickets`: auth required (JWT, role=subscriber). Body: `TicketCreateRequest(subscriber_id: UUID, cdr_reference: str, charge_paise: int, dispute_reason: str = "subscriber_initiated")`. Inserts row into `support_tickets` with `status = "OPEN"`. Returns `{"ticket_id": str, "status": "OPEN", "created_at": str}`. [Source: epics.md:1686]
  - [ ] `GET /api/v1/support/tickets`: auth required (role=subscriber). Query param `?status=OPEN` optional. Returns list of subscriber's tickets: `[{"ticket_id": str, "cdr_reference": str, "dispute_reason": str, "status": str, "created_at": str}]`. [Source: epics.md:1690; FR-28]
  - [ ] Wire router in `service_webapp/src/main.py`: `app.include_router(support_router, prefix="/api/v1/support")`.

- [ ] **Task 2: support_tickets DB queries** (AC: #2, #4)
  - [ ] Create `service_webapp/src/db/support/__init__.py` (empty).
  - [ ] Create `service_webapp/src/db/support/queries.py`:
    - `get_tickets_by_subscriber(db, subscriber_id: str, status: str | None = None) -> list[dict]` — SELECT from `support_tickets` WHERE subscriber_id = %s (AND status = %s if provided) ORDER BY created_at DESC.
  - [ ] Create `service_webapp/src/db/support/commands.py`:
    - `create_ticket(db, subscriber_id: str, cdr_reference: str, charge_paise: int, dispute_reason: str) -> dict` — INSERT into `support_tickets` returning all columns. PK is `id UUID DEFAULT uuid_generate_v7()`. [Source: V1__baseline_schema.sql:359–376; architecture.md §1.7.1 UUIDv7]
  - [ ] Check V1 migration for exact column names in `support_tickets`: likely `id, subscriber_id, cdr_reference, dispute_reason, status, created_at, resolved_at`. [Source: V1__baseline_schema.sql:359–376]

- [ ] **Task 3: `ticket_create` tool in Support Agent** (AC: #1, #2, #3)
  - [ ] In `service_webapp/src/agents/support/graph.py`, add `@tool` function `ticket_create(subscriber_id: str, cdr_reference: str, charge_paise: int) -> dict`.
  - [ ] Calls `create_ticket(db_pool, subscriber_id, cdr_reference, charge_paise, "subscriber_initiated")` using the singleton DB pool.
  - [ ] Returns `{"ticket_id": str, "message": f"Ticket #{ticket_id} has been created. Our team will review it within 48 hours."}`.
  - [ ] Dispute flow is multi-turn: agent first fetches charge via `charge_explain` (Story 5.7), presents it, waits for subscriber confirmation message, THEN calls `ticket_create`. LangGraph handles multi-turn via the conversational memory in Valkey. [Source: epics.md:1684]

- [ ] **Task 4: Balance Management Agent (A2A)** (AC: #5, #6)
  - [ ] Create `service_webapp/src/agents/balance/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/balance/graph.py`.
  - [ ] `BalanceAgentState(TypedDict)`: `msisdn: str`, `balance_paise: int | None`, `trace_id: str`.
  - [ ] Node `fetch_balance(state) -> state`: reads `balance:{msisdn}` from Valkey via `await _valkey.get(f"balance:{state['msisdn']}")`. Converts bytes to int. Sets `state["balance_paise"]`.
  - [ ] Graph: single node → END. Compile.
  - [ ] In `service_webapp/src/agents/support/graph.py`, add `@tool` function `balance_lookup(msisdn: str) -> dict`.
  - [ ] `balance_lookup` invokes: `result = await balance_graph.ainvoke({"msisdn": msisdn, "trace_id": current_trace_id})`. Returns `{"balance_paise": int, "balance_inr": f"₹{result['balance_paise']/100:.2f}"}`.
  - [ ] LangFuse: child span `name="a2a_balance_agent"` nested under Support Agent trace. [Source: epics.md:1698; FR-72]

- [ ] **Task 5: Frontend ticket confirmation rendering** (AC: #2, #3)
  - [ ] Create `frontend/src/portals/subscriber/components/TicketConfirmationBanner.tsx`.
  - [ ] Props: `{ ticket_id: string, message: string }`. Renders a green confirmation banner. [Source: ux-brief-chatbot.md]
  - [ ] Register `ticket_create` action renderer:
    ```tsx
    useCopilotAction({
      name: "ticket_create",
      render: ({ result }) => <TicketConfirmationBanner ticket_id={result.ticket_id} message={result.message} />
    });
    ```

- [ ] **Task 6: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_support_router.py`: mock DB. POST /api/v1/support/tickets → 201 with ticket_id; GET /api/v1/support/tickets → list; GET with status=OPEN filter → filtered list.
  - [ ] `service_webapp/tests/unit/test_balance_agent.py`: mock Valkey. Balance 5000 paise → returns dict with balance_paise=5000, balance_inr="₹50.00". Missing key → balance_paise=0.
  - [ ] `service_webapp/tests/unit/test_ticket_create_tool.py`: mock DB commands. Verify ticket_create returns correct message format with ticket_id.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1 migration). Create ticket → verify UUID7 PK generated, status=OPEN.

## Dev Notes

### support_tickets already in V1 — NO new migration

V1__baseline_schema.sql:359–376 creates `support_tickets`. Story 5.8 DOES NOT create a migration. The epics AC saying "a Flyway migration creates: support_tickets table" is WRONG — contradicts the memory convention "V1 = full all-domain baseline". [Source: V1__baseline_schema.sql:359; memory: story_conventions_decisions — Flyway V1 scope is FULL all-domain baseline]

### support_tickets UUIDv7

`support_tickets.id` uses `uuid_generate_v7()` per architecture §1.7.1 (transactional table). V1 baseline should already have this DDL — verify before writing commands. [Source: V1__baseline_schema.sql:359; architecture.md §1.7.1]

### Balance Management Agent vs get_balance tool (Story 5.4)

Story 5.4 has a `get_balance` tool that also reads Valkey. The Balance Management Agent (this story) is the A2A pattern — it wraps the same Valkey read in a LangGraph graph so it can be traced independently as an A2A call. For simple balance queries, the agent may choose `get_balance` (direct tool). For the AC-specific case of "wallet balance?" intent → use `balance_lookup` (A2A). This distinction is intentional per architecture §1.6.1. [Source: architecture.md §1.6.1; epics.md:1694]

### Dispute multi-turn flow

The dispute flow is:
1. Agent detects dispute intent → calls `charge_explain` (Rating Agent A2A) → presents breakdown.
2. Subscriber confirms → Agent calls `ticket_create` tool.

LangGraph manages multi-turn via the `chat_context:{session_id}` Valkey HASH (Story 5.4). The agent uses `state.context_turns` to see the subscriber's confirmation message. No new state field needed — this is standard multi-turn chatbot behaviour. [Source: epics.md:1684]

### CQRS: queries vs commands

Per architecture ARCH-4 (CQRS): `queries.py` for SELECT, `commands.py` for INSERT/UPDATE/DELETE. The support router uses:
- `GET /tickets` → `queries.get_tickets_by_subscriber()`
- `POST /tickets` → `commands.create_ticket()`

[Source: architecture.md:ARCH-4; existing pattern in db/ subdirs]

### PII in ticket cdr_reference

`cdr_reference` is a CDR ID (UUID string) — not PII. `subscriber_id` is a UUID — not PII. `dispute_reason` is a string — free text, agent must not include MSISDN/name in it. The `ticket_create` tool should pass `dispute_reason = "subscriber_initiated"` hardcoded. [Source: architecture.md:ARCH-32]

### Project Structure Notes

- New: `service_webapp/src/routers/support.py`
- New: `service_webapp/src/db/support/queries.py` and `commands.py`
- New: `service_webapp/src/agents/balance/graph.py`
- New: `frontend/src/portals/subscriber/components/TicketConfirmationBanner.tsx`
- Modified: `service_webapp/src/agents/support/graph.py` (add ticket_create + balance_lookup tools, wire balance_graph singleton)
- Modified: `service_webapp/src/main.py` (include support_router)
- No migration (support_tickets in V1).

### References

- [Source: epics.md §1.8.8 — Story 5.8 acceptance criteria]
- [Source: architecture.md §1.6.1 — Balance Management Agent A2A; ticket_create tool]
- [Source: architecture.md:FR-28 — ticket viewing via chatbot]
- [Source: architecture.md:FR-30 — disputed transaction workflow]
- [Source: architecture.md:FR-31 — Balance Management Agent integration]
- [Source: architecture.md:FR-72 — LangFuse A2A child spans]
- [Source: V1__baseline_schema.sql:359–376 — support_tickets DDL]
- [Source: memory: story_conventions_decisions — V1 full baseline, no per-story schema migrations]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
