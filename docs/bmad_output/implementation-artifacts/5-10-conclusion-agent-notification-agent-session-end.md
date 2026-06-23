---
baseline_commit: 3c5d585
---

# Story 5.10: Conclusion Agent & Notification Agent (Session End)

Status: ready-for-dev

## Story

As a **subscriber**,
I want to receive a relevant follow-up notification after my chat session if the agent determines one is warranted,
so that I'm reminded of actions I didn't complete or offers I might want to act on.

## Acceptance Criteria

1. **Given** a chatbot session ends (user closes chat or 2h TTL expires on `chat_context`), **When** the Conclusion Agent runs, **Then** it reads the session history from Valkey HASH `chat_context:{session_id}`, summarises key learnings (topics discussed, actions taken, unresolved queries), and stores them in the `support_session_learnings` table. [Source: epics.md:1748; FR-34]
2. **And** it triggers the Notification Agent (A2A) with the session summary. [Source: epics.md:1750; FR-34]
3. **Given** the Notification Agent receives the session summary, **When** it evaluates whether to send a notification, **Then** it uses `settings.chat_deployment_mini` (gpt-4o-mini) to decide: should a notification be sent? (yes/no), notification type (`RECHARGE_REMINDER | PLAN_SUGGESTION | DISPUTE_FOLLOWUP | NONE`), channel (push/SMS), when (now / +1h / +24h). [Source: epics.md:1756; FR-35]
4. **And** if the decision is to send, a notification event is published to `notification.events` Kafka topic with the decision payload. [Source: epics.md:1758]
5. **And** the Notification Agent decision and output are traced to LangFuse. [Source: epics.md:1760; FR-72]
6. **And** the `support_session_learnings` table (already in V1 baseline) is used — NO new migration required. [Source: V1__baseline_schema.sql:394–404]
7. **And** session-end trigger is fired when: (a) subscriber explicitly closes the chat panel (frontend event), or (b) a background task detects `chat_context:{session_id}` TTL expiry (2h idle). [Source: epics.md:1744; ARCH-5]

## Tasks / Subtasks

- [ ] **Task 1: Conclusion Agent LangGraph graph** (AC: #1, #2, #5)
  - [ ] Create `service_webapp/src/agents/conclusion/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/conclusion/graph.py`.
  - [ ] `ConclusionAgentState(TypedDict)`: `session_id: str`, `subscriber_id: str`, `session_history: list[dict]`, `summary: str | None`, `trace_id: str`.
  - [ ] Node `load_session_history(state) -> state`:
    - Read all `chat_context:{session_id}` HASH fields from Valkey (all `turn_N` fields).
    - Parse JSON, reconstruct chronological turn list.
    - Set `state["session_history"]`.
  - [ ] Node `summarise_session(state) -> state`:
    - LLM call (`settings.chat_deployment_mini`): prompt = "Summarise this chat session. List: (1) topics discussed, (2) actions taken (recharges, tickets), (3) unresolved queries. Be concise. Return JSON: {summary_text: str, topics: [], actions: [], unresolved: []}."
    - Input: formatted session_history.
    - Parse JSON response → `state["summary"]`.
  - [ ] Node `store_learning(state) -> state`:
    - INSERT into `support_session_learnings`: `(session_id, subscriber_id, summary_text=state["summary"])`. [Source: V1__baseline_schema.sql:394–404]
  - [ ] Node `trigger_notification(state) -> state`:
    - Invoke Notification Agent A2A: `await notification_graph.ainvoke({"session_summary": state["summary"], "subscriber_id": state["subscriber_id"], "trace_id": state["trace_id"]})`.
  - [ ] Graph edges: `load_session_history → summarise_session → store_learning → trigger_notification → END`. [Source: epics.md:1748–1750]

- [ ] **Task 2: Notification Agent LangGraph graph** (AC: #3, #4, #5)
  - [ ] Create `service_webapp/src/agents/notification/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/notification/graph.py`.
  - [ ] `NotificationAgentState(TypedDict)`: `session_summary: str`, `subscriber_id: str`, `should_send: bool | None`, `notification_type: str | None`, `channel: str | None`, `delay_hours: int | None`, `trace_id: str`.
  - [ ] Node `decide_notification(state) -> state`:
    - LLM call (`settings.chat_deployment_mini`): structured prompt with session summary.
    - System: "You are a telecom notification decision agent. Based on this chat session summary, decide if a follow-up notification is warranted. Return JSON: {should_send: bool, type: 'RECHARGE_REMINDER|PLAN_SUGGESTION|DISPUTE_FOLLOWUP|NONE', channel: 'push|sms', delay_hours: 0|1|24}."
    - Parse JSON → set state fields.
  - [ ] Node `publish_notification(state) -> state`:
    - Conditional: only run if `state["should_send"] == True`.
    - Publish to `notification.events` via KafkaProducer:
      ```python
      EventEnvelope.new(
          event_type="notification.session_end",
          payload={
              "type": state["notification_type"],
              "subscriber_id": state["subscriber_id"],
              "channel": state["channel"],
              "delay_hours": state["delay_hours"],
              "session_summary": state["session_summary"][:200]  # truncate for PII safety
          },
          trace_id=state["trace_id"]
      )
      ```
    - Key by subscriber_id on `notification.events` topic. [Source: epics.md:1758; architecture.md ARCH-11]
  - [ ] Graph: `decide_notification → (conditional: should_send?) → publish_notification → END` or `decide_notification → END` (if NONE). [Source: epics.md:1756]
  - [ ] LangFuse: trace entire Notification Agent run; child span under Conclusion Agent trace. [Source: epics.md:1760; FR-72]

- [ ] **Task 3: support_session_learnings DB commands** (AC: #1)
  - [ ] Add `store_session_learning(db, session_id: str, subscriber_id: str, summary_text: str) -> None` to `service_webapp/src/db/support/commands.py`.
  - [ ] INSERT into `support_session_learnings`. PK is `id UUID` — check V1 migration for exact DDL. The table was seeded with `uuid_generate_v7()` or `gen_random_uuid()` — verify. [Source: V1__baseline_schema.sql:394–404]
  - [ ] `support_session_learnings` schema from V1: `(id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES support_chat_sessions(id), subscriber_id UUID, summary_text TEXT, created_at TIMESTAMPTZ)`. Verify foreign key to `support_chat_sessions`. [Source: V1__baseline_schema.sql:394–404]

- [ ] **Task 4: Session-end trigger mechanism** (AC: #7)
  - [ ] Frontend trigger (explicit close): in `frontend/src/portals/subscriber/Chatbot.tsx`, when the chat panel is closed (CopilotChat `onClose` callback), call `POST /api/v1/support/chat/end` with `{ session_id }`. [Source: epics.md:1744]
  - [ ] Create `POST /api/v1/support/chat/end` in `service_webapp/src/routers/support.py`: auth required. Body: `{ session_id: str }`. Fires Conclusion Agent as `asyncio.create_task(conclusion_graph.ainvoke(...))`. Returns 202 Accepted immediately (non-blocking). [Source: architecture.md: async agent pattern]
  - [ ] Background TTL trigger: add a background task in `service_webapp/src/main.py` that polls for expired `chat_context:*` sessions every 5 minutes using Valkey `SCAN` + `TTL` check. If TTL has expired (key deleted), fire Conclusion Agent for that session. [Source: epics.md:1744; ARCH-5: 2h TTL]
  - [ ] NOTE: The TTL poll is best-effort — a process restart may miss some expirations. For MVP this is acceptable. A Valkey keyspace notification would be more reliable but requires `notify-keyspace-events` config. [Source: architecture.md: MVP scope]

- [ ] **Task 5: Wire agents at FastAPI startup** (AC: #1, #2)
  - [ ] In `service_webapp/src/main.py` lifespan: instantiate Conclusion and Notification Agent graph singletons, wire KafkaProducer to Notification Agent via `set_kafka_producer(producer)` singleton call (same pattern as tools in 5.4). [Source: service_webapp/src/main.py lifespan pattern]

- [ ] **Task 6: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_conclusion_agent.py`: mock Valkey (3 turns stored), mock LLM, mock DB.
    - Verify `load_session_history` reads all turns correctly.
    - Verify `summarise_session` calls LLM with formatted history.
    - Verify `store_learning` INSERT called with correct session_id + summary.
    - Verify `trigger_notification` calls notification_graph.ainvoke.
  - [ ] `service_webapp/tests/unit/test_notification_agent.py`: mock LLM.
    - LLM returns `{should_send: true, type: "RECHARGE_REMINDER", channel: "push", delay_hours: 1}` → KafkaProducer.publish called once.
    - LLM returns `{should_send: false, type: "NONE"}` → no Kafka publish.
  - [ ] `service_webapp/tests/unit/test_chat_end_endpoint.py`: mock conclusion_graph. POST /api/v1/support/chat/end → 202; asyncio.create_task called.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres + Valkey (testcontainers). Store turns → fire conclusion agent → verify support_session_learnings INSERT.

## Dev Notes

### support_session_learnings in V1 — NO new migration

V1__baseline_schema.sql:394–404 creates `support_session_learnings`. Story 5.10 epics AC saying "a Flyway migration creates: session_learnings table" is WRONG — contradicts V1 full baseline convention. The canonical table name is `support_session_learnings` (NOT `session_learnings`). [Source: V1__baseline_schema.sql:394; memory: story_conventions_decisions]

### Conclusion Agent is async — never on hot path

The Conclusion Agent runs AFTER session end, never during chat. It must be launched as `asyncio.create_task()` (fire-and-forget) from the `POST /api/v1/support/chat/end` endpoint. The endpoint returns 202 immediately. The agent may take 5–15 seconds to run. [Source: architecture.md: async agent execution pattern]

### KafkaProducer in Notification Agent

The Notification Agent publishes to `notification.events` using the same `KafkaProducer` singleton wired in `service_webapp/src/main.py` lifespan. The Notification Agent accesses it via module-level `_kafka_producer` singleton (same pattern as other tool singletons). [Source: service_webapp/src/main.py lifespan existing producer setup]

### PII in session summary

The LLM summarises session history. The summary text stored in `support_session_learnings.summary_text` MUST NOT contain raw MSISDN, full name, or card numbers. The Conclusion Agent's summarisation prompt must instruct: "Never include personal identifiable information (MSISDN, name, address, card numbers) in the summary." The Kafka payload also truncates summary to 200 chars. [Source: architecture.md:ARCH-32]

### support_chat_sessions FK constraint

`support_session_learnings.session_id` has a FK to `support_chat_sessions.id`. Before inserting a learning, ensure the `support_chat_sessions` row exists. In Story 5.4, when a chat session starts, a row should be inserted into `support_chat_sessions` (add this to the Story 5.4 Support Agent node startup logic if not already done). [Source: V1__baseline_schema.sql:377–391 support_chat_sessions; V1__baseline_schema.sql:394–396 support_session_learnings FK]

### LangFuse A2A tracing chain

The trace chain for session-end is: `Conclusion Agent trace → child span: summarise (LLM call) → child span: a2a_notification_agent → child span: decide (LLM call) → child span: publish`. Pass `trace_id` through `RatingAgentState` and `NotificationAgentState` to maintain the parent trace across A2A calls. [Source: FR-72; LangFuse SDK nested spans]

### Background TTL poll — SCAN pattern

Valkey `SCAN 0 MATCH chat_context:* COUNT 100` returns cursor + keys. Check each key's TTL — if TTL returns -2 (key expired/deleted), the session has ended. Store active session IDs in a separate Valkey SET `active_chat_sessions` (add at session start in Story 5.4, remove at session end). This avoids expensive SCAN on production. Use the SET to detect stale sessions instead. [Source: Valkey docs; architecture.md ARCH-5]

### Project Structure Notes

- New: `service_webapp/src/agents/conclusion/graph.py`
- New: `service_webapp/src/agents/notification/graph.py`
- Modified: `service_webapp/src/db/support/commands.py` (add store_session_learning)
- Modified: `service_webapp/src/routers/support.py` (add POST /chat/end)
- Modified: `service_webapp/src/main.py` (wire conclusion/notification singletons, background TTL task)
- Modified: `frontend/src/portals/subscriber/Chatbot.tsx` (add onClose → POST /chat/end)
- No migration (support_session_learnings in V1).

### References

- [Source: epics.md §1.8.10 — Story 5.10 acceptance criteria]
- [Source: architecture.md §1.6.1 — Conclusion Agent + Notification Agent A2A]
- [Source: architecture.md:FR-34 — Conclusion Agent (session learning + Notification Agent trigger)]
- [Source: architecture.md:FR-35 — Notification Agent (A2A session-end notification decision)]
- [Source: architecture.md:FR-72 — LangFuse nested span tracing]
- [Source: architecture.md:ARCH-5 — chat_context:* Valkey HASH, 2h TTL]
- [Source: architecture.md:ARCH-32 — PII hygiene]
- [Source: V1__baseline_schema.sql:394–404 — support_session_learnings DDL]
- [Source: V1__baseline_schema.sql:377–391 — support_chat_sessions DDL]
- [Source: memory: story_conventions_decisions — V1 full baseline; canonical table names]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
