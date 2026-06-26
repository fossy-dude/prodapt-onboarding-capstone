---
baseline_commit: 89d48fe
---

# Story 6.3: Fraud Detection Agent — LLM-Powered Risk Analysis

Status: ready-for-dev

## Story

As a **fraud analyst**,
I want flagged CDR events to be analysed by a LangGraph-powered Fraud Detection Agent using 7-day subscriber history,
so that genuine fraud is distinguished from false positives before entering the case queue.

## Acceptance Criteria

1. **Given** an event is published to `cdr.fraud.flagged`, **When** the Fraud Detection Agent processes it (asynchronously — never in the balance deduction hot path), **Then** it fetches the subscriber's last 7 days of CDR history from Postgres. (ARCH-14, FR-61) [Source: epics.md:1838]
2. **And** it invokes GPT-5.4 with a structured prompt containing: rule triggered, CDR pattern, subscriber history summary, and outputs a verdict: `confirmed_fraud | false_positive | needs_review` with a `confidence_score` (0.0–1.0). [Source: epics.md:1840]
3. **And** the agent is implemented as a LangGraph async graph in `service_webapp/src/agents/fraud/graph.py`. [Source: epics.md:1842]
4. **And** the full agent run is traced to LangFuse: input (CDR event + history), output (verdict), model, token usage, latency. (FR-72) [Source: epics.md:1844]
5. **Given** the verdict is `confirmed_fraud` or `needs_review`, **When** the agent completes, **Then** a `fraud_cases` row is inserted with: case_id (UUIDv7), msisdn, verdict, confidence_score, rule_triggered, agent_trace_id, status = OPEN. (FR-62) [Source: epics.md:1850]
6. **And** a `fraud.alerts` event is published with the case summary. (FR-62) [Source: epics.md:1852]
7. **Given** the verdict is `false_positive`, **When** the agent completes, **Then** the `fraud_events` row is marked as `resolved = false_positive`; no `fraud_cases` row is created. [Source: epics.md:1858]

## Tasks / Subtasks

- [ ] **Task 1: Flyway migration V12 — fraud_cases columns** (AC: #5, #7)
  - [ ] Create `service_webapp/db/migrations/V12__fraud_cases_extensions.sql`.
  - [ ] Version: V11 is Story 6.2 (fraud_pre_screener); this is V12. Renumber only if a lower version is still free — never collide with V10 (usage MV) or V11.
  - [ ] Reuse existing semantically-equal columns (audit 2026-06-25 confirms ALL fraud_cases columns are unused outside DDL):
    | AC column | Existing column | Action |
    |---|---|---|
    | `case_id` | `id` (UUIDv7 PK) | reuse |
    | `confidence_score` | `risk_score` (NUMERIC(5,4), 0-1) | reuse |
    | `rule_triggered` | `triggered_by` (VARCHAR(50)) | reuse |
    | `detected_at` | `created_at` | reuse (row insert time = detection) |
    | `status` | `status` (VARCHAR(20)) | reuse (uppercase values OPEN/UNDER_REVIEW/RESOLVED) |
    | `msisdn` | — | ADD |
    | `verdict` | — | ADD (fraud_type is the category, NOT the verdict) |
    | `agent_trace_id` | — | ADD |
    | `analyst_notes` | — | ADD (forward-compat for 6.4 PATCH) |
    | `resolved_by` | — | ADD (forward-compat for 6.4 PATCH) |
  - [ ] SQL (additive only):
    ```sql
    ALTER TABLE fraud_cases
        ADD COLUMN IF NOT EXISTS msisdn         VARCHAR(15),
        ADD COLUMN IF NOT EXISTS verdict        VARCHAR(20),
        ADD COLUMN IF NOT EXISTS agent_trace_id UUID,
        ADD COLUMN IF NOT EXISTS analyst_notes  TEXT,
        ADD COLUMN IF NOT EXISTS resolved_by    VARCHAR(200);

    CREATE INDEX IF NOT EXISTS idx_fraud_cases_verdict ON fraud_cases (verdict);
    CREATE INDEX IF NOT EXISTS idx_fraud_cases_msisdn  ON fraud_cases (msisdn);
    ```
  - [ ] `subscriber_id` already NOT NULL with FK; `msisdn` is denormalized for queue display + blacklist join (resolved from `identity_subscribers` at insert).
  - [ ] Note: the existing `status` default is `'open'`. The agent writes uppercase `'OPEN'`. Either keep the lowercase default (existing rows are empty anyway) or `ALTER COLUMN status SET DEFAULT 'OPEN'`. Prefer setting the default to `'OPEN'` for consistency with the AC status vocabulary.

- [ ] **Task 2: fraud db layer (CQRS)** (AC: #1, #5, #7)
  - [ ] Create `service_webapp/src/db/fraud/__init__.py`, `queries.py` (SELECT), `commands.py` (INSERT/UPDATE).
  - [ ] `queries.py`:
    - `get_7day_cdr_summary(conn, subscriber_id: UUID) -> dict` —
      ```sql
      SELECT
        COUNT(*)                                                              AS cdr_count,
        COUNT(*) FILTER (WHERE cdr_type='voice')                              AS voice_count,
        COUNT(*) FILTER (WHERE cdr_type='data')                               AS data_count,
        COALESCE(SUM(duration_seconds) FILTER (WHERE cdr_type='voice'), 0)    AS voice_seconds,
        COALESCE(SUM(volume_mb)        FILTER (WHERE cdr_type='data'),  0)    AS data_mb,
        COUNT(*) FILTER (WHERE roaming=TRUE)                                  AS roaming_count,
        MAX(start_time)                                                       AS last_event_at
      FROM billing_cdr_events
      WHERE subscriber_id = %(subscriber_id)s AND start_time >= NOW() - INTERVAL '7 days'
      ```
    - `get_7day_recharge_summary(conn, subscriber_id: UUID) -> dict` — count/sum of `recharge_orders WHERE status='COMPLETED' AND created_at >= NOW()-7d`.
    - `get_sim_swap_history(conn, subscriber_id: UUID) -> list[dict]` — `SELECT registration_id, sim_serial, submitted_at FROM identity_registrations WHERE subscriber_id=%s AND registration_type='SIM_SWAP' AND submitted_at >= NOW()-7d ORDER BY submitted_at DESC`.
    - `resolve_msisdn(conn, subscriber_id: UUID) -> str` — `SELECT msisdn FROM identity_subscribers WHERE id=%s`.
    - `get_fraud_event(conn, cdr_id: UUID) -> dict | None` — load the flagged event (for rule_triggered + context).
  - [ ] `commands.py`:
    - `create_fraud_case(conn, *, subscriber_id, msisdn, verdict, confidence_score, rule_triggered, agent_trace_id, fraud_type) -> UUID` — INSERT into fraud_cases returning `id`. Map: `confidence_score`→`risk_score`, `rule_triggered`→`triggered_by`, `status='OPEN'`.
    - `mark_fraud_event_resolved(conn, cdr_id: UUID, resolution: str, agent_trace_id: UUID) -> None` — `UPDATE fraud_events SET resolved=%s, agent_trace_id=%s WHERE cdr_id=%s`.

- [ ] **Task 3: Fraud Detection Agent graph** (AC: #1, #2, #3)
  - [ ] Create `service_webapp/src/agents/fraud/__init__.py`, `graph.py`.
  - [ ] Follow the Rating-agent pattern (NOT the CopilotKit support pattern): plain `TypedDict` state, single analysis node → END, compiled ONCE into a module singleton `fraud_graph = build_fraud_graph()`, invoked via `await fraud_graph.ainvoke({...})`. No `bind_tools`, no ToolNode, no recursion_limit (deterministic single-pass). [Source: 5-7 rating graph pattern; agents/rating/graph.py]
  - [ ] State:
    ```python
    class FraudAgentState(TypedDict):
        cdr_id: str
        subscriber_id: str
        rule_triggered: str
        cdr_event: dict            # the flagged CDR payload
        history_summary: dict      # 7-day CDR + recharge + sim-swap summary
        verdict: str               # confirmed_fraud | false_positive | needs_review
        confidence_score: float
        reason: str
        trace_id: str
    ```
  - [ ] Node `analyze_risk(state) -> dict`:
    1. Resolve msisdn + load 7-day history via `get_*` queries (inside `async with fraud_db.transaction() as conn:`).
    2. Build the structured prompt (system): rule triggered, CDR pattern (from `cdr_event`), subscriber history summary. Instruct: "Classify as `confirmed_fraud`, `false_positive`, or `needs_review`. Return JSON `{verdict, confidence_score: 0.0-1.0, reason}`." Verdict labels EXACTLY these three (6.1 contract).
    3. Invoke the LLM: build `AzureChatOpenAI(azure_deployment=settings.chat_deployment, temperature=0.0, ...)` (GPT-5.4 / the full model, NOT mini). Parse JSON; validate verdict ∈ the three labels and `0.0 ≤ confidence_score ≤ 1.0` (defensive `float()` cast — NULL/garbage → default `needs_review` at confidence 0.0).
    4. Return `{verdict, confidence_score, reason}`.
  - [ ] Build graph: `builder = StateGraph(FraudAgentState); builder.add_node("analyze_risk", analyze_risk); builder.set_entry_point("analyze_risk"); builder.set_finish_point("analyze_risk"); return builder.compile()`. [Source: support/graph.py compile pattern — `set_entry_point`, no recursion_limit]

- [ ] **Task 4: Persistence + alert publish** (AC: #5, #6, #7)
  - [ ] After `ainvoke`, branch on verdict (this branching is in the CONSUMER, not the graph — the graph only classifies):
    - `confirmed_fraud` or `needs_review`: `create_fraud_case(...)` (verdict, confidence_score→risk_score, rule_triggered→triggered_by, agent_trace_id=trace_id, status='OPEN'); publish `fraud.alerts` envelope (`event_type="fraud.alert"`, key=msisdn, payload = case summary: `case_id, msisdn[-4:], verdict, confidence_score, rule_triggered, detected_at`).
    - `false_positive`: `mark_fraud_event_resolved(cdr_id, 'false_positive', agent_trace_id)`; NO fraud_cases row; NO alert.
  - [ ] Alert publish via a `KafkaProducer` — service_webapp already has a producer for lifespan consumers; reuse the same broker producer as the notification/simulator broadcasters. Key=`msisdn` (ARCH-10). Preserve `trace_id` (NFR-17).

- [ ] **Task 5: Consumer wiring in service_webapp lifespan** (AC: #1)
  - [ ] In `service_webapp/src/main.py` lifespan, add a 5th `AIOKafkaConsumer("cdr.fraud.flagged", group_id="fraud-detection-agent", auto_offset_reset="latest", value_deserializer=lambda v: json.loads(v.decode()))` background task, mirroring the existing 4 consumers (simulator-trace-broadcaster, notification-portal-broadcaster, notification-dispatcher, cdr-notifications). [Source: architecture digest §10; main.py lifespan pattern]
  - [ ] Per flagged message: parse envelope → `await fraud_graph.ainvoke({cdr_id, subscriber_id, rule_triggered, cdr_event, trace_id})` → Task 4 persistence/branch. This consumer is the async path (ARCH-14) — entirely off the balance hot path (different process/service).
  - [ ] Dedup on `cdr_id` (at-least-once): before invoking, check `get_fraud_event(cdr_id)`; if already `resolved` or a `fraud_cases` row exists for this cdr_id, skip. Use the `uq_fraud_events_cdr` unique constraint (6.2) as the backstop.

- [ ] **Task 6: LangFuse tracing (implement the 6.1 template)** (AC: #4)
  - [ ] In `analyze_risk`, wrap the LLM call:
    ```python
    client = get_langfuse_client()   # Langfuse | None, gated on settings.langfuse_enabled
    if client is not None:
        with client.start_as_current_observation(
            name="fraud_agent_node", as_type="generation",
            input={"rule_triggered": ..., "cdr_summary_7d": _redact(history), "subscriber_history": _redact(...)},
            model=settings.chat_deployment,
        ) as observation:
            response = await llm.ainvoke(messages)
            observation.update(
                output={"verdict": verdict, "confidence_score": conf, "reason": reason},
                usage_details={"input": response.usage_metadata["input_tokens"],
                               "output": response.usage_metadata["output_tokens"],
                               "total": response.usage_metadata["total_tokens"]},
            )
    ```
  - [ ] PII hygiene (ARCH-32/NFR-16): `_redact()` masks msisdn to `[-4:]`, never logs subscriber UUID/name/address or verbatim call content. Store `agent_trace_id` on the fraud_cases/fraud_events row linking to this observation.
  - [ ] Do NOT use the unused `@trace_agent` decorator (as-built uses inline `start_as_current_observation`). Do NOT hand-roll `__enter__/__exit__` + bare `except: pass`. [Source: 5-4 LangFuse pattern; langfuse v4 API; memory: copilotkit-support-agent-story-5-4]
  - [ ] If `client is None` (langfuse disabled / no key), run untraced (no error). [Source: architecture.md#1.10.2]

- [ ] **Task 7: Settings + DI + deps** (AC: #3)
  - [ ] Add `set_fraud_db(db)` / `get_fraud_db()` / `_require_fraud_db()` singleton in `src/agents/fraud/graph.py` (mirror `set_support_adapters`/`set_retriever`); wire `set_fraud_db(db)` in `main.py` lifespan, reset to `None` in the lifespan `finally` (review patch — leaked singletons). [Source: 5-4 singleton pattern; memory: copilotkit-support-agent-story-5-4]
  - [ ] LLM build must be a no-op-safe import when Azure secrets absent (lint/test boot without keys) — guard construction or lazily build inside the node. [Source: 5-4 model registration guard]
  - [ ] Deps already present: `langgraph>=0.2`, `langchain-core>=0.2`, `langchain-openai>=0.2`, `langfuse>=2`, `aiokafka>=0.11`, `psycopg[async,pool]`. Confirm `langchain-openai` (for `AzureChatOpenAI`) is in BOTH `lint` and `test` tox env deps (it is, per 5.4). No new runtime deps.

- [ ] **Task 8: Tests** (AC: #1–#7)
  - [ ] `service_webapp/tests/unit/test_fraud_graph.py` (mocked LLM + DB): verdict parsing — valid JSON → correct verdict/confidence; garbage/NULL → `needs_review`/0.0; verdict outside the 3 labels → rejected/defaulted; confidence clamped 0-1.
  - [ ] `service_webapp/tests/unit/test_fraud_persistence.py`: confirmed_fraud → `create_fraud_case` INSERT with risk_score/triggered_by/status='OPEN'; false_positive → `mark_fraud_event_resolved('false_positive')` + no case row. Assert column mappings (risk_score, triggered_by — NOT confidence_score/rule_triggered column names which do not exist).
  - [ ] `service_webapp/tests/unit/test_fraud_redaction.py`: `_redact` masks msisdn; no raw subscriber_id/name in the observation input.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1+V11+V12) — seed a flagged `fraud_events` row + 7-day CDR history, invoke the graph with a stubbed LLM returning `confirmed_fraud`, assert `fraud_cases` row + `fraud.alerts` publish.
  - [ ] Connect to the 6.1 eval harness: `just eval-fraud` with the real `fraud_graph` wired (remove the ImportError fallback once 6.3 lands) must hit `tp_rate >= 0.75` (NFR-13) against `fraud_golden.json`. This is the acceptance gate linking 6.1↔6.3.

## Dev Notes

### Agent pattern — Rating-style, NOT CopilotKit support-style

The fraud agent is a background classifier invoked from a Kafka consumer, NOT a CopilotKit chat agent. Use the `agents/rating/graph.py` pattern: plain `TypedDict` state, single deterministic node, module singleton compiled at import, `await fraud_graph.ainvoke(...)`. Do NOT use `CopilotKitState`, `ToolNode`, `bind_tools`, or `recursion_limit` — those are for the ReAct chat supervisor. The graph ONLY classifies; all persistence/branching/alert-publish happens in the consumer that calls it. [Source: 5-7 rating graph; agents/rating/graph.py; support/graph.py compile pattern]

### Identity comes from the Kafka event, not a JWT (contrast with 5.4)

The biggest Epic-5 lesson (5.4/5.6): resolve subscriber identity server-side from the JWT via a contextvar — NEVER from LLM tool args or CopilotKitState. That lesson is about CHAT tools. This agent is a BATCH consumer: `subscriber_id` arrives in the trusted `cdr.fraud.flagged` envelope (written by the cdr-pipeline screener from `billing_cdr_events.subscriber_id`), not from any client. So resolve msisdn via `resolve_msisdn(subscriber_id)` from the DB — do not trust any msisdn in a client payload. There is no JWT contextvar here. [Source: 5-4/5-6 IDOR lesson; memory: copilotkit-support-agent-story-5-4]

### fraud_cases column reuse — write risk_score/triggered_by, NOT confidence_score/rule_triggered

The AC names `confidence_score` and `rule_triggered`, but the existing columns are `risk_score` and `triggered_by`. INSERT/SELECT MUST use the real column names:
```sql
INSERT INTO fraud_cases
  (subscriber_id, msisdn, fraud_type, verdict, risk_score, triggered_by,
   agent_trace_id, evidence, status)
VALUES (...);
```
`fraud_type` (existing) = the rule category (e.g. `'SIM_SWAP'`); `verdict` (new) = `confirmed_fraud`/etc. `confidence_score`→`risk_score`; `rule_triggered`→`triggered_by`. Verifying against the actual schema is the #1 code-review failure mode — do not assume AC column names exist. [Source: V1__baseline_schema.sql:424-440; code-review-2026-06-23; audit 2026-06-25]

### Verdict label standardization

Use EXACTLY `confirmed_fraud | false_positive | needs_review` (6.1 canonical). architecture.md §1.6.2 (`confirmed`) and the readiness report (`CONFIRMED_RISK`) differ — ignore those. The LLM prompt must constrain output to these three labels; validate post-parse. [Source: epics.md:1840; 6-1 dev notes]

### async, off the hot path

The agent consumer runs in service_webapp's lifespan, consuming `cdr.fraud.flagged`. Typical LLM latency 5-15s is accepted (architecture.md#1.13.5 callout 2): during that window additional CDRs process normally. This is fine — the screener (6.2) already recorded the `fraud_events` row; the agent enriches it. Do NOT block the balance consumer (separate process, ARCH-14). [Source: architecture.md#1.4.3, #1.13.5; ARCH-14]

### 6.1 eval harness is the accuracy gate

Story 6.1 ships the harness with an `ImportError`-fallback stub. Once `agents/fraud/graph.py` exists (this story), the harness auto-wires the real graph and `just eval-fraud` enforces `tp_rate >= 0.75` (NFR-13). Treat the eval as the acceptance test for classification quality. [Source: 6-1 Task 4; epics.md:1790; NFR-13]

### Azure deployment-name gotcha

`settings.chat_deployment` ("gpt-5.4") is an Azure DEPLOYMENT name, not a model name. Valid key+endpoint still 404s if the deployment name is a placeholder — the user must set `CHAT_DEPLOYMENT` to a real Azure portal deployment. With no `AZURE_OPENAI_API_KEY`, the graph must still import/build without error (guard). [Source: 5-2 Dev Agent Record; memory: eval-harness-story-5-2]

### LangFuse — inline context-manager, no decorator, no hand-rolled CM

Use `start_as_current_observation(...)` (langfuse v4) inline in the node. The `@trace_agent` decorator exists but is unused and leaks `self` — do not use it. Never hand-roll `__enter__/__exit__` with bare `except: pass`. PII-redact every input (msisdn[-4:], no raw UUID/name). [Source: 5-4 LangFuse pattern; architecture.md#1.10.2; ARCH-32; memory: copilotkit-support-agent-story-5-4]

### Project Structure Notes

- New migration: `service_webapp/db/migrations/V12__fraud_cases_extensions.sql` (5 additive columns on fraud_cases; reuse risk_score/triggered_by/created_at/status/id)
- New package: `service_webapp/src/agents/fraud/{__init__.py,graph.py}`
- New db layer: `service_webapp/src/db/fraud/{__init__.py,queries.py,commands.py}`
- Modified: `service_webapp/src/main.py` (fraud.alerts consumer + set_fraud_db + lifespan reset)
- Modified: `service_webapp/src/core/observability/langfuse.py` only if a shared redaction helper is missing (otherwise inline `_redact` in graph.py)
- New tests: `tests/unit/test_fraud_graph.py`, `test_fraud_persistence.py`, `test_fraud_redaction.py`; `tests/integration/test_fraud_agent.py`
- No cdr-pipeline changes (the screener is 6.2; this agent consumes what it produces). No frontend.

### References

- [Source: epics.md:1824-1858 — Story 6.3 acceptance criteria]
- [Source: epics.md#1.2.3 ARCH-14 — agent async off hot path; ARCH-10 — topics; ARCH-32 — PII]
- [Source: epics.md#1.2.2 FR-61, FR-62, FR-72 — agent escalation, supervisor notification, LangFuse]
- [Source: architecture.md §1.6.2 — fraud verdict classification; §1.10.2 LangFuse coverage; §1.4.3 async; §1.13.5 callout 2]
- [Source: V1__baseline_schema.sql:424-440 — fraud_cases DDL; 178-189 billing_cdr_events]
- [Source: audit 2026-06-25 — fraud_cases columns unused; risk_score/triggered_by reusable]
- [Source: 5-7-rating-agent-charge-breakdown-explanation.md — Rating graph pattern; 5-4 CopilotKit agent — singleton DI, LangFuse, model guard, IDOR lesson]
- [Source: 6-1-eval-harness-fraud-detection-agent-accuracy.md — verdict labels, trace template, eval gate]
- [Source: memory: copilotkit-support-agent-story-5-4 — singleton reset, langfuse v4, IDOR contextvar; memory: eval-harness-story-5-2 — Azure deployment-name]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
