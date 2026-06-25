---
baseline_commit: 89d48fe
---

# Story 6.1: Eval Harness — Fraud Detection Agent Accuracy

Status: ready-for-dev

## Story

As a **QA engineer**,
I want a fraud detection evaluation harness with a golden fixture set before any fraud agent code is written,
so that fraud agent implementations can be validated against accuracy targets from day one.

## Acceptance Criteria

1. **Given** the fraud eval harness is set up, **When** the fraud eval suite runs, **Then** a fixture dataset of 50 CDR sequences is stored in `service_webapp/evals/fixtures/fraud_golden.json`: 25 true-positive fraud cases (SIM swap, velocity abuse, suspicious recharge) and 25 true-negative clean cases. [Source: epics.md:1786]
2. **And** an evaluator asserts that a Fraud Detection Agent callable correctly classifies each case as `confirmed_fraud | false_positive | needs_review`. [Source: epics.md:1788]
3. **And** the target true-positive rate ≥ 75% is enforced as a CI gate (NFR-13). [Source: epics.md:1790; NFR-13]
4. **And** a LangFuse trace template is defined for fraud agent calls: node name, input (7-day CDR summary), output (verdict), model, `confidence_score`. [Source: epics.md:1792]
5. **And** the harness accepts any LangGraph fraud graph callable and runs against the fixture set. [Source: epics.md:1794]

## Tasks / Subtasks

- [ ] **Task 1: Create fraud eval package structure** (AC: #1, #5)
  - [ ] Create directory tree (sibling of existing chatbot evals — NOT inside `src/`):
    ```
    service_webapp/evals/fraud/
    ├── __init__.py
    ├── conftest.py
    ├── test_fraud_accuracy.py
    └── fixtures/
        └── fraud_golden.json
    ```
  - [ ] `evals/fraud/__init__.py` empty.
  - [ ] `evals/fraud/conftest.py`: skip ALL tests in this dir if `AZURE_OPENAI_API_KEY == ""` with `pytest.skip("Azure OpenAI not configured")`; provide `golden_fraud_fixtures` fixture (loads `fixtures/fraud_golden.json`) and `stub_fraud_graph_callable` fixture (returns a callable that classifies from `fixture["expected_verdict"]` for harness self-test).

- [ ] **Task 2: Golden fraud fixture dataset** (AC: #1)
  - [ ] Create `service_webapp/evals/fraud/fixtures/fraud_golden.json`. JSON array of 50 entries. Schema per entry:
    ```json
    {
      "id": "tp-simswap-001",
      "category": "sim_swap",
      "subscriber_id": "<uuid-v4 hex>",
      "msisdn_last4": "1234",
      "cdr_summary": {
        "window_days": 7,
        "event_count": 42,
        "cdr_types": ["voice", "data"],
        "roaming_ratio": 0.12,
        "velocity_peak_hourly": 58,
        "recharges_24h": 4,
        "sim_swap_in_window": true,
        "geo_anomaly": false
      },
      "rule_triggered": "SIM_SWAP",
      "expected_verdict": "confirmed_fraud",
      "tags": ["sim_swap", "true_positive"]
    }
    ```
  - [ ] 25 true-positive entries: ~9 SIM swap (`rule_triggered=SIM_SWAP`), ~8 velocity abuse (`VELOCITY`), ~8 suspicious recharge (`SUSPICIOUS_RECHARGE`). Each `expected_verdict=confirmed_fraud`.
  - [ ] 25 true-negative clean entries: normal usage patterns, `rule_triggered=null`, `expected_verdict=false_positive`. Distribute so that ~5 are borderline (`expected_verdict=needs_review`) to exercise the three-way classifier.
  - [ ] All data synthetic — no real MSISDN (use `msisdn_last4` only, PII hygiene ARCH-32/NFR-16). `subscriber_id` are synthetic UUID v4 hex strings, not real DB rows.

- [ ] **Task 3: Fraud graph callable contract + evaluator** (AC: #2, #5)
  - [ ] Create `service_webapp/evals/fraud/fraud_evaluator.py`.
  - [ ] Define the callable contract the harness accepts:
    ```python
    FraudGraphCallable = Callable[[dict, dict], "FraudVerdict"]
    # (cdr_summary: dict, context: dict) -> FraudVerdict
    ```
    `FraudVerdict` is a dataclass:
    ```python
    @dataclass
    class FraudVerdict:
        verdict: Literal["confirmed_fraud", "false_positive", "needs_review"]
        confidence_score: float   # 0.0-1.0
        rule_triggered: str | None
        reason: str
    ```
  - [ ] `run_fraud_evaluation(graph_callable, fixtures) -> FraudEvalReport` where:
    ```python
    @dataclass
    class FraudEvalReport:
        total: int
        true_positives: int       # expected confirmed_fraud AND got confirmed_fraud
        false_negatives: int      # expected confirmed_fraud AND got (false_positive|needs_review)
        true_negatives: int       # expected false_positive AND got false_positive
        false_positives: int      # expected false_positive AND got confirmed_fraud
        tp_rate: float            # true_positives / total_expected_fraud
        results: list[dict]       # per-case {id, expected, actual, pass}
    ```
  - [ ] Pass logic: TP case passes iff `actual.verdict == expected_verdict` (or `needs_review` acceptable for `confirmed_fraud` expected cases — see dev notes: acceptable_downgrade). TN case passes iff `actual.verdict == false_positive`.
  - [ ] Verdict labels are EXACTLY `confirmed_fraud | false_positive | needs_review` — these are the canonical labels for Epic 6 (variance across docs noted in dev notes).

- [ ] **Task 4: Accuracy test + CI gate** (AC: #3)
  - [ ] Create `service_webapp/evals/fraud/test_fraud_accuracy.py`.
  - [ ] Test `test_fraud_tp_rate_meets_nfr13()` (marked `@pytest.mark.slow`):
    - Loads `golden_fraud_fixtures`.
    - Resolves `fraud_graph_callable`: prefer a real fraud graph if `service_webapp/src/agents/fraud/graph.py` is importable (Story 6.3, not yet built) — wrap with a `try/except ImportError` fallback to `stub_fraud_graph_callable`. This keeps the gate runnable today (stub) and meaningful once 6.3 lands.
    - Runs `run_fraud_evaluation(...)`, asserts `tp_rate >= 0.75` (NFR-13). Test fails non-zero if below threshold.
    - Writes report to `service_webapp/evals/reports/fraud_latest.json`.
  - [ ] Test `test_fraud_classifier_label_space()`: asserts every verdict emitted by the callable is one of the three canonical labels (guards against `CONFIRMED_RISK`/`confirmed` drift).

- [ ] **Task 5: LangFuse trace template** (AC: #4)
  - [ ] Create `service_webapp/evals/fraud/langfuse_template.py` defining the trace shape Story 6.3 MUST emit:
    ```python
    FRAUD_AGENT_TRACE = {
        "name": "fraud_agent_node",
        "as_type": "generation",
        "input_fields": {"rule_triggered", "cdr_summary_7d", "subscriber_history"},
        "output_fields": {"verdict", "confidence_score", "reason"},
        "metadata_fields": {"model", "trace_id"},
    }
    ```
  - [ ] This module is a TEMPLATE/CONTRACT only — it documents the trace fields; Story 6.3 implements the actual `start_as_current_observation` call. No LangFuse SDK call in this story (no agent exists yet).
  - [ ] Test `test_fraud_trace_template_complete()`: asserts every required field present in `FRAUD_AGENT_TRACE` (PII-redacted: `cdr_summary_7d` must mask MSISDN to `[-4:]`, never raw subscriber UUID/name).

- [ ] **Task 6: `just eval-fraud` recipe and tox env** (AC: #3)
  - [ ] Add `[tool.tox.env.eval-fraud]` in `service_webapp/pyproject.toml`:
    - `deps`: same as `test` env PLUS `deepeval>=2.0`, `openai>=1.0` (mirror the existing `eval` env — needed only because the real graph in 6.3 imports langchain/deepeval-adjacent tooling; the stub path needs none, but keep parity so 6.3 is a drop-in).
    - `commands`: `python -m pytest service_webapp/evals/fraud/ -m slow -v --tb=short` (explicit path, NO `{posargs}` — empty positional would re-trigger `tests/` collection, the 5.2 trap).
    - `setenv`: inherit `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `CHAT_DEPLOYMENT`, `CHAT_DEPLOYMENT_MINI`.
    - `package = "skip"`.
    - `pythonpath`: `["src", "."]` (so `evals.fraud` resolves `from src...` and the 6.3 graph import works once it exists).
  - [ ] Add `eval-fraud` recipe to `service_webapp/justfile`:
    ```
    eval-fraud:
        cd service_webapp && uvx --with tox-uv tox -e eval-fraud
    ```
  - [ ] Add `eval-fraud` recipe to root `justfile` delegating to service_webapp (mirror the root `eval` recipe).
  - [ ] Do NOT add fraud deps to `lint` or `test` envs (quarantine rule). The `evals/fraud/` package is outside `src/` so pyrefly skips it; ruff lints it (clean).
  - [ ] Verify default `just test` collects 0 items from `evals/fraud/` (pytest `testpaths=["tests"]` gate already covers this — confirm, do not change `testpaths`).

- [ ] **Task 7: Unit tests for evaluator logic** (AC: #2)
  - [ ] Create `service_webapp/tests/unit/test_fraud_evaluator.py` (NOT slow-marked — runs in `just test`; pure-Python with mocked callable).
  - [ ] Mock `FraudGraphCallable`. Test: all-correct classifications → `tp_rate=1.0`; one TP downgraded to `needs_review` → counts as pass (acceptable_downgrade) but tracked; one TP downgraded to `false_positive` → false_negative, `tp_rate` drops; threshold at exactly 0.75 → pass; below 0.75 → the gate test would fail (assert report field, not the gate, here — gate lives in slow test).

## Dev Notes

### Canonical verdict labels — resolve doc variance

The verdict label set is inconsistent across the planning docs:
- epics.md Story 6.3: `confirmed_fraud | false_positive | needs_review` (most specific, CANONICAL for Epic 6).
- architecture.md §1.6.2: `confirmed | false_positive | needs_review`.
- PRD FR-61: `confirmed | false positive | needs review`.
- implementation-readiness-report: `CONFIRMED_RISK, UNCLEAR, FALSE_ALARM`.

This story and all Epic 6 agent work STANDARDIZE on `confirmed_fraud | false_positive | needs_review`. The `test_fraud_classifier_label_space()` test enforces this. [Source: epics.md:1840; user decision 2026-06-25]

### acceptable_downgrade — TP vs needs_review

A true-positive case whose expected verdict is `confirmed_fraud` but the agent returns `needs_review` is an ACCEPTABLE downgrade (the analyst will review it — it is not lost). It is counted as a pass for the gate but flagged in the report so `false_negatives` is distinct from `missed`. A downgrade to `false_positive` is a true miss (false_negative). This matches the PRD counter-metric "false positive fraud escalation rate". [Source: prd.md §1.8 Success Metrics]

### TP rate denominator — NFR-13 wording

NFR-13: "Fraud detection escalation accuracy ≥ 75% true positive rate (agent-confirmed vs. supervisor-cleared)." Denominator = the 25 expected-`confirmed_fraud` fixtures. `tp_rate = true_positives / 25`. Gate at ≥ 0.75 (≥ 18.75 → 19 of 25). [Source: epics.md:1790; NFR-13]

### evals/fraud/ is outside src/ — intentional

Same rationale as Story 5.2: `service_webapp/evals/` is a sibling of `src/`, not inside it. Pyrefly does not type-check it; ruff lints it. `evals/fraud/` imports from `service_webapp/src/` via `pythonpath=["src","."]`. The real fraud graph import (`from agents.fraud.graph import build_fraud_graph`) resolves once Story 6.3 creates it; the `ImportError` fallback keeps 6.1 green standalone. [Source: 5-2-eval-harness-llm-as-judge-deepeval-scaffolding.md; memory: eval-harness-story-5-2]

### Tox per-env-deps discipline

Per [[app_code_toolchain]]: new imports go in BOTH `lint` and `test` — EXCEPT eval-only heavy deps (`deepeval`, `openai`), which stay quarantined in the eval envs. The fraud eval uses the same quarantine. If `fraud_evaluator.py` is ever imported by non-eval code, revisit; for 6.1 it is standalone (only consumed by `evals/fraud/` tests). [Source: memory: app_code_toolchain]

### Avoid the empty-posarg trap

The eval tox command MUST use an explicit path (`service_webapp/evals/fraud/`) with NO `{posargs}`. Story 5.2 hit a bug where an empty positional re-triggered `tests/` collection. [Source: 5-2 Dev Agent Record; memory: eval-harness-story-5-2]

### LangFuse template — contract, not call

This story defines the trace SHAPE (`langfuse_template.py`). Story 6.3 implements the real `start_as_current_observation(name="fraud_agent_node", as_type="generation", input=<7-day CDR summary, PII-redacted>, output={verdict, confidence_score})` using the existing `service_webapp/src/core/observability/langfuse.py` `get_langfuse_client()` (langfuse v4 context-manager API, gated on `settings.langfuse_enabled`). Do NOT instantiate a deepeval/langfuse model manually here. [Source: 5-4 agent graph LangFuse pattern; architecture.md §1.10.2; memory: copilotkit-support-agent-story-5-4]

### graph_callable contract evolution

Story 5.2 used `Callable[[str, dict], str]` (question, context) -> answer. Fraud differs: input is a structured CDR summary (not a free-text question), output is a structured `FraudVerdict` (not a string). So the fraud callable is its own typed contract `Callable[[dict, dict], FraudVerdict]`, deliberately separate from the chatbot one — do NOT force one contract to fit both. Both share the harness philosophy (accept any graph callable + run against fixtures). [Source: epics.md:1794; 5-2 graph_callable contract]

### Azure deployment-name gotcha

Valid key + endpoint is NOT sufficient. Placeholder deployment names (`gpt-4o-mini`) return `404 DeploymentNotFound` even with successful auth. The eval tox env `passenv` carries `CHAT_DEPLOYMENT` / `CHAT_DEPLOYMENT_MINI`, which the user must set to real Azure portal deployment names. Once 6.3 wires the real graph with `azure_deployment=settings.chat_deployment` (gpt-5.4), the gate becomes meaningful; with no `AZURE_OPENAI_API_KEY` the suite skips cleanly (AC conftest guard). [Source: 5-2 Dev Agent Record; memory: eval-harness-story-5-2]

### Project Structure Notes

- New files: `service_webapp/evals/fraud/{__init__.py,conftest.py,test_fraud_accuracy.py,langfuse_template.py,fraud_evaluator.py,fixtures/fraud_golden.json}` (outside `src/`)
- New unit test: `service_webapp/tests/unit/test_fraud_evaluator.py`
- Tox env: new `eval-fraud` env in `service_webapp/pyproject.toml`
- Justfile: new `eval-fraud` recipe in `service_webapp/justfile` + root `justfile`
- No migration, no FastAPI router, no agent code, no frontend.

### References

- [Source: epics.md:1772-1794 — Story 6.1 acceptance criteria]
- [Source: epics.md#1.2.2 NFR-13 — fraud TP rate ≥ 75%]
- [Source: prd.md §1.8 Success Metrics — fraud escalation accuracy + false-positive counter-metric]
- [Source: architecture.md §1.6.2 — fraud verdict classification]
- [Source: architecture.md §1.10.2 — LangFuse coverage (every node, tokens + latency)]
- [Source: architecture.md#1.2.3 ARCH-32, epics.md#1.2.2 NFR-16 — PII hygiene (msisdn[-4:], no raw UUID/name)]
- [Source: 5-2-eval-harness-llm-as-judge-deepeval-scaffolding.md — evals/ layout, graph_callable contract, tox eval env, conftest skip guard]
- [Source: memory: eval-harness-story-5-2 — harness layout, just eval tox env, empty-posarg trap, Azure deployment-name gotcha]
- [Source: memory: app_code_toolchain — tox per-env-deps discipline, slow test pattern]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
