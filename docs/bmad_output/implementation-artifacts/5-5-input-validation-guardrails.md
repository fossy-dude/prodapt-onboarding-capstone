---
baseline_commit: 3c5d585
---

# Story 5.5: Input Validation Guardrails

Status: ready-for-dev

## Story

As a **platform engineer**,
I want the chatbot to reject malformed, adversarial, or suspicious inputs before they reach the LLM,
so that the system is protected from prompt injection and abuse.

## Acceptance Criteria

1. **Given** a subscriber sends a message to the chatbot, **When** the guardrail middleware processes it, **Then** messages exceeding 2,000 characters are rejected with: "Your message is too long. Please keep it under 2,000 characters." [Source: epics.md:1606; FR-27]
2. **And** messages containing prompt injection patterns (e.g., "ignore previous instructions", "system:") are rejected with: "I can only help with billing and account queries." [Source: epics.md:1608]
3. **And** messages with no semantic overlap with telecom/billing topics (cosine similarity < 0.2 against a topic seed embedding) are rejected with: "I'm a billing assistant and can only help with account and plan queries." [Source: epics.md:1610]
4. **And** all rejected messages are logged to `support_guardrail_rejections` table with: `session_id`, `rejection_reason`, `message_hash` (SHA-256 of raw message — NOT raw content for PII safety). [Source: epics.md:1612; ARCH-32]
5. **And** a Flyway migration creates the `support_guardrail_rejections` table (UUIDv7 PK, as it is a high-insert transactional log). [Source: architecture.md §1.7.1 UUID strategy; user decision 2026-06-23]
6. **And** the guardrail runs as a pre-processing node in the LangGraph Support Agent graph (Story 5.4) — rejections short-circuit the graph and return an error message without calling the LLM. [Source: epics.md:1604; architecture.md §1.6.1]

## Tasks / Subtasks

- [ ] **Task 1: Flyway migration — support_guardrail_rejections** (AC: #4, #5)
  - [ ] Create `service_webapp/db/migrations/VN__support_guardrail_rejections.sql`. Assign next available migration version at implementation time by checking existing files in `service_webapp/db/migrations/` (currently V1–V5; V6+ claimed by Epic 3–4 stories — use `ls` to determine actual next number).
  - [ ] DDL:
    ```sql
    CREATE TABLE support_guardrail_rejections (
        id              UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
        session_id      UUID NOT NULL,
        rejection_reason VARCHAR(50) NOT NULL
                         CHECK (rejection_reason IN ('TOO_LONG', 'PROMPT_INJECTION', 'OFF_TOPIC')),
        message_hash    CHAR(64) NOT NULL,  -- SHA-256 hex
        created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
    CREATE INDEX idx_sgr_session_id ON support_guardrail_rejections (session_id);
    CREATE INDEX idx_sgr_created_at ON support_guardrail_rejections (created_at DESC);
    ```
  - [ ] Apply `set_modified_at()` trigger only if `modified_at` column exists — this table is append-only (no `modified_at` column). The trigger definition in V2 must NOT be applied here. [Source: V2__modified_at_trigger.sql — append-only tables excluded]
  - [ ] Note: `uuid_generate_v7()` requires `pg_uuidv7` extension (already enabled in V1 baseline). [Source: architecture.md §1.7.1; V1__baseline_schema.sql]

- [ ] **Task 2: Guardrail validator module** (AC: #1–#3)
  - [ ] Create `service_webapp/src/agents/guardrails/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/guardrails/validator.py`.
  - [ ] Dataclass `GuardrailResult`: `passed: bool, rejection_reason: str | None, response_message: str | None`.
  - [ ] Class `InputGuardrail`:
    - Constructor: `__init__(self, azure_client: AzureOpenAI, embedding_deployment: str)`.
    - Lazily computed class-level `_topic_seed_embedding: list[float]` — the embedding of a seed text: `"billing balance plan recharge usage data voice SMS account telecom MVNO subscriber"`. Computed once on first call via Azure OpenAI embeddings. [Source: epics.md:1610]
    - Method `async def validate(self, message: str) -> GuardrailResult`:
      1. Length check: `if len(message) > 2000` → return rejection with reason `TOO_LONG`.
      2. Injection check: scan for any of the patterns: `["ignore previous instructions", "ignore above", "system:", "assistant:", "disregard", "forget your instructions", "new instructions:", "override"]` (case-insensitive) → reason `PROMPT_INJECTION`.
      3. Semantic check: embed `message` → cosine similarity vs `_topic_seed_embedding`. If similarity < 0.2 → reason `OFF_TOPIC`. `cosine_similarity(a, b) = dot(a, b) / (norm(a) * norm(b))`. [Source: epics.md:1610]
    - Method `def _cosine_similarity(self, a: list[float], b: list[float]) -> float`: pure Python implementation using `math.sqrt` and `sum()`. No numpy dependency for this utility. [Source: toolchain — avoid heavy deps in hot path]

- [ ] **Task 3: Audit log write** (AC: #4)
  - [ ] In `service_webapp/src/agents/guardrails/validator.py`, add function `async def log_rejection(db: AsyncConnection, session_id: str, reason: str, raw_message: str) -> None`.
  - [ ] Compute `message_hash = hashlib.sha256(raw_message.encode()).hexdigest()`. [Source: epics.md:1612]
  - [ ] INSERT into `support_guardrail_rejections` (session_id, rejection_reason, message_hash). Use existing `db/support/queries.py` pattern or create `service_webapp/src/db/support/queries.py` if Story 5.8 hasn't created it yet. [Source: architecture.md CQRS: queries.py for SELECT, commands.py for INSERT — or use raw psycopg execute for simple INSERT]
  - [ ] The INSERT uses the `sboai_app` role (write-capable). PII note: raw message is NEVER stored — only SHA-256 hash. [Source: ARCH-32]

- [ ] **Task 4: Wire guardrail into Support Agent graph** (AC: #6)
  - [ ] In `service_webapp/src/agents/support/graph.py` (Story 5.4): add `guardrail_node` as the FIRST node in the graph.
  - [ ] `guardrail_node(state: SupportAgentState) -> SupportAgentState`:
    - Validate `state.messages[-1]["content"]` via `await _guardrail.validate(message)`.
    - If rejected: set `state.messages.append({"role": "assistant", "content": result.response_message})`, set a `rejected: bool = True` flag on state; log rejection via `log_rejection(...)`.
    - If passed: set `rejected = False`, continue.
  - [ ] Conditional edge after `guardrail_node`: if `state.rejected == True` → `END`; else → `support_agent_node`.
  - [ ] Module-level singleton `_guardrail: InputGuardrail` — set at startup via `set_guardrail(guardrail)` analogous to `set_retriever()` pattern. [Source: story 5.3 singleton pattern]

- [ ] **Task 5: Wire guardrail at FastAPI startup** (AC: #3)
  - [ ] In `service_webapp/src/main.py` lifespan: after Azure OpenAI client is constructed, call `set_guardrail(InputGuardrail(azure_client=client, embedding_deployment=settings.embedding_model))`. The guardrail uses the embedding deployment for semantic checks. [Source: service_webapp/src/main.py lifespan pattern]

- [ ] **Task 6: Tests** (AC: #1–#5)
  - [ ] `service_webapp/tests/unit/test_input_guardrail.py`:
    - Length check: message of 2001 chars → `passed=False, reason="TOO_LONG"`.
    - Injection check: "ignore previous instructions please" → `passed=False, reason="PROMPT_INJECTION"`.
    - Off-topic (mocked similarity 0.05): "write me a poem" → `passed=False, reason="OFF_TOPIC"`.
    - Valid message (mocked similarity 0.8): "what is my balance?" → `passed=True`.
    - Cosine similarity edge case: zero vector → similarity returns 0.0 (no division by zero).
  - [ ] `service_webapp/tests/unit/test_guardrail_log.py`: mock DB. Verify `log_rejection` inserts correct session_id, reason, and SHA-256 hash (not raw message). Verify PII not stored.
  - [ ] Integration test (`@pytest.mark.slow`): real Postgres with V1 + VN migrations. Insert guardrail rejection row → verify hash stored correctly.

## Dev Notes

### support_guardrail_rejections — UUIDv7, NEW migration

This table is NOT in the V1 baseline (verified: `grep guardrail service_webapp/db/migrations/V1__baseline_schema.sql` returns nothing). A new Flyway migration IS required. The table is transactional (log of rejection events, potentially high insert rate) → UUIDv7 per architecture §1.7.1. [Source: architecture.md §1.7.1; user decision 2026-06-23]

### Canonical table name: support_guardrail_rejections

Epics use `guardrail_rejections` but this violates arch §1.7.1 domain prefix convention. Architecture canonical = `support_guardrail_rejections` (support_ domain, same as `support_tickets`, `support_chat_sessions`). [Source: user decision 2026-06-23; architecture.md §1.7.1]

### Cosine similarity — pure Python, no numpy

The similarity check runs on every message — keep it dependency-free. Pure Python with `math.sqrt` is sufficient for 1536-dim vectors in a chat latency context (microseconds). Do NOT add numpy to runtime deps for this single use case.

### Topic seed embedding — lazy compute once

The topic seed embedding is computed from Azure OpenAI at first call and cached as a class attribute. It does NOT need to be recomputed on each request. At startup, optionally pre-warm by calling `validate()` with a dummy message. If Azure OpenAI is unreachable (empty key), the semantic check defaults to `passed=True` to avoid blocking all chat messages when LLM is unconfigured. Log a warning when falling back. [Source: architecture.md:NFR — availability over strict guardrails in dev]

### Guardrail SHORT-CIRCUITS the graph

The guardrail node must return a response directly via AG-UI without invoking the LLM. In CopilotKit's LangGraph integration, this means appending an `assistant` message to state and routing to `END`. CopilotKit will stream this message as `TextMessageContent` events. The subscriber sees the rejection message immediately — no LLM call made, no LangFuse trace started (or minimal trace with `rejected=True` annotation). [Source: epics.md:1604]

### ARCH-32 PII hygiene

`message_hash` stores SHA-256 of the raw message. This is acceptable for audit purposes (idempotent, one-way). The raw message text MUST NOT be stored in any DB column, log, or LangFuse span. [Source: architecture.md:ARCH-32]

### Project Structure Notes

- New: `service_webapp/src/agents/guardrails/validator.py`
- New: `service_webapp/db/migrations/VN__support_guardrail_rejections.sql` (assign VN at implementation)
- Modified: `service_webapp/src/agents/support/graph.py` (add guardrail_node, conditional edge)
- Modified: `service_webapp/src/main.py` (wire guardrail singleton)
- No frontend changes, no new runtime deps (guardrail uses openai already added in 5.3/5.4).

### References

- [Source: epics.md §1.8.5 — Story 5.5 acceptance criteria]
- [Source: architecture.md §1.7.1 — UUID strategy, domain prefix convention]
- [Source: architecture.md:ARCH-32 — PII hygiene rules]
- [Source: architecture.md:FR-27 — Input validation guardrails]
- [Source: V1__baseline_schema.sql — confirms support_guardrail_rejections NOT in V1]
- [Source: V2__modified_at_trigger.sql — append-only tables pattern]
- [Source: memory: story_conventions_decisions — DB naming: architecture canonical]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
