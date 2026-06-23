---
baseline_commit: 3c5d585
---

# Story 5.4: CopilotKit Runtime & Support Agent Graph

Status: ready-for-dev

## Story

As a **subscriber**,
I want to query my balance and plan details, get FAQ answers, and maintain conversational context across turns through the chatbot,
so that I can resolve my queries without navigating multiple screens.

## Acceptance Criteria

1. **Given** the CopilotKit runtime is wired as a FastAPI router at `POST /api/chat/stream`, **When** a subscriber sends a message, **Then** the LangGraph Support Agent graph processes the message with AG-UI streaming protocol. [Source: epics.md:1574–1578; ARCH-13]
2. **And** the agent has access to tools: `get_balance` (reads Valkey `balance:{msisdn}`), `get_plan` (DB query), `get_usage`, `rag_search` (Story 5.3). [Source: epics.md:1580; FR-22, FR-23, FR-26]
3. **And** conversational context (last 10 turns) is stored and retrieved from Valkey HASH `chat_context:{session_id}` with 2h TTL. [Source: epics.md:1582; FR-25, ARCH-5]
4. **And** `useCopilotReadable` hooks expose balance, active plan, and session context to the agent graph so it can answer without extra API calls. [Source: epics.md:1584; ARCH-23]
5. **And** every agent node execution is traced to LangFuse with: node name, input, output, model (`settings.chat_deployment_mini`), token usage, latency. [Source: epics.md:1586; FR-72]
6. **And** the chatbot response streams token-by-token to the frontend via AG-UI SSE events. [Source: epics.md:1588]
7. **And** the frontend `Chatbot.tsx` component in `frontend/src/portals/subscriber/` renders the chat UI using `<CopilotChat>`. [Source: architecture.md:264–269; ARCH-23]

## Tasks / Subtasks

- [ ] **Task 1: Support Agent LangGraph graph** (AC: #1, #2, #5)
  - [ ] Create `service_webapp/src/agents/support/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/support/graph.py`.
  - [ ] Import: `from langgraph.graph import StateGraph, END`, `from copilotkit.langgraph import CopilotKitState`.
  - [ ] Define `SupportAgentState(CopilotKitState)` — extends CopilotKitState with: `session_id: str`, `msisdn: str`, `messages: list[dict]`, `context_turns: list[dict]`.
  - [ ] Define tool functions (as LangGraph tools via `@tool` decorator from `langchain_core.tools`):
    - `get_balance(msisdn: str) -> dict`: reads Valkey `balance:{msisdn}` via `redis.AsyncRedis` singleton. Returns `{"balance_paise": int, "balance_inr": str}`.
    - `get_plan(subscriber_id: str) -> dict`: queries `plans_subscriptions JOIN plans_plans` WHERE status='active'. Returns plan name, expiry, data/voice/SMS limits.
    - `get_usage(subscriber_id: str, days: int = 30) -> dict`: queries `billing_cdr_events` SUM by type (voice_seconds, data_mb, sms_count) for last N days.
    - `rag_search(query: str) -> list[dict]`: delegates to `service_webapp/src/agents/rag/retriever.rag_search` (Story 5.3). Returns chunk dicts.
  - [ ] Supervisor node `support_agent_node`: LLM call using `AzureOpenAI` with `settings.chat_deployment_mini`, tool-calling enabled, system prompt: "You are a billing and account assistant for an MVNO. Answer only billing, plan, usage, and account queries. Use tools to fetch real data. Follow TRAI regulations. Never reveal PII beyond MSISDN last-4." [Source: architecture.md:ARCH-32]
  - [ ] Build graph: `builder = StateGraph(SupportAgentState)`. Add nodes: `support_agent_node`, tool executor node. Add conditional edges for tool calls → tool executor → support_agent_node loop. Set `FINISH` condition when no more tool calls. Compile: `graph = builder.compile()`. [Source: architecture.md §1.6.1]
  - [ ] LangFuse tracing: wrap each node execution with LangFuse span — `name=node_name, input=state_snapshot, output=response, model=settings.chat_deployment_mini`. Use `CallbackHandler` from `langfuse.langchain` if using LangChain bridge, or direct `langfuse_client.trace()`. [Source: epics.md:1586; FR-72]

- [ ] **Task 2: Conversational context in Valkey** (AC: #3)
  - [ ] In `support_agent_node`: on each turn, load `chat_context:{session_id}` HASH from Valkey (up to 10 most recent turn JSON strings), prepend to messages list as prior context. After LLM response, append new `{role: "user", content: ...}` + `{role: "assistant", content: ...}` to HASH (field = turn index), set TTL=7200s. [Source: epics.md:1582; ARCH-5]
  - [ ] Valkey HASH structure: field=`"turn_{n}"`, value=`json.dumps({"role": ..., "content": ...})`. Keep fields 0–9 (sliding window: delete oldest when > 10 turns).

- [ ] **Task 3: CopilotKit runtime FastAPI router** (AC: #1, #6)
  - [ ] Create `service_webapp/src/routers/chat.py`.
  - [ ] Import: `from copilotkit.integrations.fastapi import add_fastapi_endpoint`, `from copilotkit import CopilotKitSDK, LangGraphAgent`.
  - [ ] Register agent: `sdk = CopilotKitSDK(agents=[LangGraphAgent(name="support_agent", description="Billing assistant", graph=graph)])`.
  - [ ] Call `add_fastapi_endpoint(app, sdk, "/api/chat/stream")` — this registers the streaming endpoint. [Source: architecture.md:275]
  - [ ] Wire into `service_webapp/src/main.py`: `from routers.chat import setup_copilotkit; setup_copilotkit(app)` (or import and call in the app factory). [Source: service_webapp/src/main.py existing router pattern]

- [ ] **Task 4: Frontend Chatbot component** (AC: #4, #7)
  - [ ] Create `frontend/src/portals/subscriber/Chatbot.tsx`.
  - [ ] Wrap subscriber portal root with `<CopilotKit runtimeUrl="/api/chat/stream">`. Find the root layout component in `frontend/src/portals/subscriber/` and add the wrapper. [Source: architecture.md:268; ux-brief-chatbot.md]
  - [ ] Inside the portal, add `<CopilotChat className="sboai-chatbot-panel" instructions="You are a billing assistant..." />` — floating bottom-right panel (CSS: `position: fixed; bottom: 24px; right: 24px; z-index: 1000`).
  - [ ] Add `useCopilotReadable` hooks in the portal layout:
    ```tsx
    useCopilotReadable({ description: "subscriber_balance", value: balance });
    useCopilotReadable({ description: "active_plan", value: activePlan });
    useCopilotReadable({ description: "chat_session", value: { session_id: sessionId } });
    ```
    `balance` and `activePlan` sourced from existing React Query hooks (Stories 3.2/3.4). `session_id` generated with `useId()` or `crypto.randomUUID()` on mount. [Source: epics.md:1584; ARCH-23]
  - [ ] Install frontend deps: add `@copilotkit/react-ui` and `@copilotkit/react-core` to `frontend/package.json` then `npm install`. [Source: architecture.md:100]

- [ ] **Task 5: Settings and tox deps** (AC: #5)
  - [ ] `service_webapp/src/core/config.py`: confirm `chat_deployment_mini` and `chat_deployment` are present (added in Story 5.2). If Story 5.2 is not yet merged, add them here.
  - [ ] `service_webapp/pyproject.toml` runtime deps: add `langgraph>=0.2`, `copilotkit>=0.1`, `langchain-core>=0.2`, `langchain-openai>=0.1`.
  - [ ] Add same deps to `[tool.tox.env.lint] deps` AND `[tool.tox.env.test] deps`. [Source: memory: app_code_toolchain — tox per-env-deps discipline]
  - [ ] Do NOT add `weasyprint`, `scikit-learn`, `pymilvus`, `copilotkit` (heavy native libs) to the tox test env build step — they are in deps list so pyrefly resolves types but `package = "skip"` avoids compilation. [Source: memory: app_code_toolchain]

- [ ] **Task 6: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_support_agent_tools.py`: mock Valkey (`AsyncRedis`), mock DB. Test `get_balance` returns paise int; `get_plan` returns plan dict; `get_usage` returns aggregated counts; `rag_search` delegates to retriever mock.
  - [ ] `service_webapp/tests/unit/test_chat_context.py`: test Valkey HASH sliding window — adding turn 11 evicts turn 0; context loaded correctly from HASH.
  - [ ] Integration test (`@pytest.mark.slow`): requires real Valkey (testcontainers). Test context save/load roundtrip. Skip if `DOCKER_HOST` not set.

## Dev Notes

### CopilotKit Python SDK integration pattern

`copilotkit` Python SDK (v0.1+) wires into FastAPI via `add_fastapi_endpoint` (or `CopilotKitRemoteEndpoint` depending on version). The key is that LangGraph graph must use `CopilotKitState` as the state mixin — this enables AG-UI `StateSnapshot` events to fire on state transitions. Read the installed `copilotkit` SDK docs at implementation time — API may differ slightly by version. [Source: architecture.md:272–278]

### Tool dependencies via singleton pattern

LangGraph `@tool` functions cannot easily receive dependency injection. Use module-level singletons set at FastAPI startup:
- `_valkey: AsyncRedis` — set via `set_valkey(client)` call in `main.py` lifespan
- `_db_pool: AsyncConnectionPool` — set via `set_db_pool(pool)` call
- `_langfuse: Langfuse | None` — set if `settings.langfuse_enabled`

The tool functions access these singletons. This is intentional — see Story 5.3's `set_retriever()` pattern. [Source: service_webapp/src/main.py lifespan existing pattern]

### AG-UI streaming — token-by-token

CopilotKit's `add_fastapi_endpoint` handles AG-UI event marshalling automatically when the LangGraph graph streams tokens. Enable streaming in the LangGraph graph via `graph.stream(...)` with `stream_mode="values"`. CopilotKit translates this to `TextMessageContent` AG-UI events. Do NOT implement custom SSE logic — CopilotKit handles it. [Source: architecture.md §1.6.1]

### Valkey HASH TTL

`EXPIRE chat_context:{session_id} 7200` after every write. Valkey's `EXPIRE` resets the TTL on each interaction, so the 2h window slides from the last message. This is correct behaviour — a session that's been idle for 2h expires. [Source: epics.md:1582; ARCH-5]

### Frontend .gitignore catch (from memory)

Root `.gitignore` line ~17 `lib/` silently ignores `frontend/src/lib/`. If CopilotKit generates any files under `src/lib/`, check they are tracked. Use `git status --short` after `npm install` + build. [Source: memory: app_code_toolchain — Frontend .gitignore catch]

### msisdn extraction from JWT

The Support Agent needs `msisdn` to call `get_balance`. Extract from the JWT's `sub` claim or custom claim set by Cognito. The existing FastAPI JWT middleware (Story 1.8) injects subscriber info into `request.state.subscriber`. The CopilotKit endpoint must receive the JWT and pass `msisdn` to the agent state. Implement via a CopilotKit `before_request` hook or by extracting from the `Authorization` header in the route handler before calling `sdk.process_request()`.

### ARCH-32 PII in spans

LangFuse spans must NOT include raw MSISDN, name, or address. Use `msisdn[-4:]` in any trace labels. Tool inputs/outputs logged to LangFuse should redact MSISDN: `"msisdn": msisdn[-4:]`. [Source: architecture.md:ARCH-32]

### Project Structure Notes

- New: `service_webapp/src/agents/support/` (graph, tools)
- New: `service_webapp/src/routers/chat.py`
- New: `frontend/src/portals/subscriber/Chatbot.tsx`
- Modified: `service_webapp/src/main.py` (wire CopilotKit + singleton setup)
- Modified: `service_webapp/src/core/config.py` (add deployment names if not from 5.2)
- Modified: `service_webapp/pyproject.toml` (add langgraph, copilotkit, langchain-core, langchain-openai)
- Modified: `frontend/package.json` (add @copilotkit/react-ui, @copilotkit/react-core)
- No migration, no new DB tables.

### References

- [Source: epics.md §1.8.4 — Story 5.4 acceptance criteria]
- [Source: architecture.md §1.6.1 — CopilotKit diagram + AG-UI protocol]
- [Source: architecture.md:ARCH-13 — POST /api/chat/stream runtime URL]
- [Source: architecture.md:ARCH-23 — useCopilotReadable hooks]
- [Source: architecture.md:ARCH-5 — Valkey key domains, chat_context TTL]
- [Source: architecture.md:ARCH-32 — PII hygiene]
- [Source: architecture.md:FR-22, FR-23, FR-26 — get_balance, get_plan, rag_search]
- [Source: architecture.md:FR-72 — LangFuse agent tracing]
- [Source: memory: app_code_toolchain — tox per-env-deps, PYTHONPATH=src, singleton pattern]
- [Source: memory: app_code_toolchain — Frontend .gitignore catch]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
