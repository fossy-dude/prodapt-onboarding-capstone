---
baseline_commit: 3c5d585
---

# Story 5.2: Eval Harness — LLM-as-Judge & DeepEval Scaffolding

Status: ready-for-dev

## Story

As a **QA engineer**,
I want an evaluation harness with LLM-as-Judge rubrics and DeepEval metrics wired up before any agent code is written,
so that every agent story can be validated against quality targets from the first implementation.

## Acceptance Criteria

1. **Given** the eval harness is set up, **When** `just eval` runs the eval suite, **Then** a LLM-as-Judge evaluator is implemented in `service_webapp/evals/judges/response_quality.py` with rubrics for: response relevance (does the answer address the question?), factual accuracy (is the answer consistent with the knowledge base?). [Source: epics.md:1524; FR-73]
2. **And** a DeepEval test suite is configured in `service_webapp/evals/deepeval/test_chatbot_quality.py` with metrics: `FaithfulnessMetric`, `AnswerRelevancyMetric`, `HallucinationMetric`. [Source: epics.md:1526; FR-74]
3. **And** a fixture dataset of 20 golden Q&A pairs is stored in `service_webapp/evals/fixtures/chatbot_golden.json` covering balance (4), plan (4), recharge (4), dispute (4), and FAQ (4) queries. [Source: epics.md:1528]
4. **And** the harness accepts any LangGraph graph callable and fixture set — `graph_callable: Callable[[str, dict], str]` — making it reusable for all Epic 5 agent stories. [Source: epics.md:1530]
5. **And** target thresholds: LLM-as-Judge ≥ 80% pass rate, Hallucination < 5% (evaluated against golden fixtures). [Source: epics.md:1532; NFR-11, NFR-12]
6. **And** eval results are written to `service_webapp/evals/reports/latest.json`; `just eval` exits non-zero if thresholds are not met. [Source: epics.md:1534]
7. **And** all eval tests are marked `@pytest.mark.slow` and skipped in `just test` (standard gate) — they run only via `just eval`. [Source: user decision 2026-06-23; memory: slow test pattern]

## Tasks / Subtasks

- [ ] **Task 1: Create evals directory structure** (AC: #1–#4)
  - [ ] Create directory tree:
    ```
    service_webapp/evals/
    ├── __init__.py
    ├── judges/
    │   ├── __init__.py
    │   └── response_quality.py
    ├── deepeval/
    │   ├── __init__.py
    │   └── test_chatbot_quality.py
    ├── fixtures/
    │   └── chatbot_golden.json
    └── reports/           # gitignored; created at runtime
    ```
  - [ ] Add `service_webapp/evals/` to `service_webapp/.gitignore` rule for `reports/` only (keep fixtures and source tracked).

- [ ] **Task 2: LLM-as-Judge evaluator** (AC: #1, #4, #5)
  - [ ] Create `service_webapp/evals/judges/response_quality.py`.
  - [ ] Class `ResponseQualityJudge`:
    - Constructor: `__init__(self, azure_client: AzureOpenAI, deployment: str)` — takes Azure OpenAI client (from `openai` SDK: `from openai import AzureOpenAI`).
    - Method `evaluate(self, question: str, answer: str, context: str) -> JudgeResult` where `JudgeResult` is a dataclass: `passed: bool, relevance_score: float, accuracy_score: float, reason: str`.
    - Rubric prompt (system): "You are an evaluation judge for a telecom billing assistant. Score the answer on: (1) Relevance (0.0–1.0): does it directly address the question? (2) Factual accuracy (0.0–1.0): is it consistent with the provided context? Return JSON: {relevance: float, accuracy: float, reason: str}."
    - Pass threshold: relevance ≥ 0.7 AND accuracy ≥ 0.7.
  - [ ] Function `run_judge_evaluation(graph_callable, fixtures, judge) -> EvalReport` where `EvalReport` is a dataclass: `total: int, passed: int, pass_rate: float, results: list[JudgeResult]`.
  - [ ] Use model: `settings.chat_deployment_mini` (gpt-4o-mini deployment) — cheaper for judge calls. [Source: architecture.md:98]

- [ ] **Task 3: DeepEval test suite** (AC: #2, #5, #7)
  - [ ] Create `service_webapp/evals/deepeval/test_chatbot_quality.py`.
  - [ ] Use `deepeval` library: `from deepeval import evaluate`, `from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric, HallucinationMetric`, `from deepeval.test_case import LLMTestCase`.
  - [ ] Configure DeepEval to use Azure OpenAI: set `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION` env vars (DeepEval reads these from environment).
  - [ ] Mark all test functions with `@pytest.mark.slow` so they are excluded from `just test` gate.
  - [ ] Test function `test_faithfulness_on_golden_fixtures()`: loads `chatbot_golden.json`, calls a stub `graph_callable` (returns fixture's expected_answer for testing), asserts `FaithfulnessMetric` score ≥ 0.8 on each case.
  - [ ] Test function `test_hallucination_below_threshold()`: asserts `HallucinationMetric` < 0.05 across golden fixtures.
  - [ ] Add `conftest.py` in `service_webapp/evals/deepeval/` that skips all tests if `AZURE_OPENAI_API_KEY == ""` with `pytest.skip("Azure OpenAI not configured")`.

- [ ] **Task 4: Golden fixture dataset** (AC: #3)
  - [ ] Create `service_webapp/evals/fixtures/chatbot_golden.json`. Schema:
    ```json
    [
      {
        "id": "balance-001",
        "category": "balance",
        "question": "What is my current balance?",
        "context": "Subscriber MSISDN[-4:] 1234 has balance 5000 paise (₹50.00).",
        "expected_answer": "Your current balance is ₹50.00.",
        "tags": ["balance", "inquiry"]
      },
      ...
    ]
    ```
  - [ ] Provide 20 entries: 4 balance, 4 plan, 4 recharge, 4 dispute, 4 FAQ (telecom terms, roaming, data rollover). All synthetic data — no real MSISDN/PII.

- [ ] **Task 5: `just eval` target and deps** (AC: #6, #7)
  - [ ] Add `just eval` recipe to `service_webapp/justfile`:
    ```
    eval:
        cd service_webapp && uvx --with tox-uv tox -e eval
    ```
  - [ ] Add `[tool.tox.env.eval]` in `service_webapp/pyproject.toml`:
    - `deps`: same as `test` env PLUS `deepeval>=2.0`, `openai>=1.0`
    - `commands`: `python -m pytest service_webapp/evals/ -m slow -v --tb=short`
    - `setenv`: inherit `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`
    - `package = "skip"`
  - [ ] Add `deepeval>=2.0` and `openai>=1.0` to tox `eval` env deps only (NOT to `lint` or `test` envs — keeps standard CI fast).
  - [ ] Add `eval-reports/` to `service_webapp/.gitignore` to avoid committing generated reports.

- [ ] **Task 6: Settings extension** (AC: #1)
  - [ ] Add to `service_webapp/src/core/config.py` `Settings`:
    ```python
    chat_deployment_mini: str = "gpt-4o-mini"
    chat_deployment: str = "gpt-4o"
    ```
  - [ ] These are Azure OpenAI deployment names (not model names) — the user sets them to match their Azure portal deployment. [Source: architecture.md:98; Azure OpenAI docs]

- [ ] **Task 7: Unit tests for judge evaluator** (AC: #1, #4)
  - [ ] Create `service_webapp/tests/unit/test_response_quality_judge.py`.
  - [ ] Mock `AzureOpenAI` client. Test: relevant+accurate answer → `passed=True`; irrelevant answer → `passed=False`; below threshold scores → `passed=False`.
  - [ ] Do NOT mark with `@pytest.mark.slow` — these are unit tests with mocked LLM, run in standard `just test`.

## Dev Notes

### evals/ is outside src/ — intentional

`service_webapp/evals/` is at the service_webapp root (alongside `src/`, `tests/`, `db/`), NOT inside `src/`. This mirrors the Target State `eval-service` separation. The `evals/` package imports from `service_webapp/src/` modules via `sys.path` manipulation in conftest.py or by running from `service_webapp/` with `PYTHONPATH=src`. [Source: user decision 2026-06-23; architecture.md §1.5.2]

### Tox per-env-deps discipline (from memory)

Per [[app_code_toolchain]]: every story's new imports must be added to BOTH `lint` env deps (so pyrefly resolves them) AND `test` env deps. For `deepeval` and `openai` — these are eval-only, so they go in the NEW `eval` tox env only. Do NOT add them to `lint` or `test` envs. Add `openai>=1.0` to `lint` deps only if the `response_quality.py` module is imported by non-eval code (it won't be in Story 5.2 since it's standalone). Revisit in Story 5.4 when Azure OpenAI is integrated into the main agent graph.

### Stub graph_callable for Story 5.2

In Story 5.2, no real LangGraph agent exists yet (Story 5.4 builds it). The harness must accept a `graph_callable: Callable[[str, dict], str]` so that:
- Story 5.2 tests use a stub: `lambda question, context: fixture["expected_answer"]`
- Story 5.4+ tests wire in the real `support_agent_graph.invoke`

This makes the harness useful immediately AND as a regression gate later.

### DeepEval Azure OpenAI configuration

DeepEval >= 2.0 supports Azure OpenAI via env vars. Do NOT instantiate a `deepeval.models.AzureOpenAI` model manually — set env vars and let DeepEval auto-configure. The `conftest.py` skip guard prevents eval tests from failing in CI where keys are absent.

### Azure OpenAI model names

Architecture says "GPT-5.4-mini and GPT-5.4" — these are Azure deployment names, not model names. The actual model deployed in Azure could be `gpt-4o-mini` or any model the user configures. Story 5.2 uses `settings.chat_deployment_mini` as the deployment name for judge calls. [Source: architecture.md:98]

### slow test pattern (from memory)

Per [[app_code_toolchain]]: integration tests marked `slow`+`integration`, skipped by default (`-m "not slow"`). Eval tests follow same convention: `@pytest.mark.slow`. The `just eval` tox env explicitly runs `-m slow` so they only execute there. [Source: app_code_toolchain memory]

### Project Structure Notes

- New files: `service_webapp/evals/` tree (outside `src/`)
- Settings change: `service_webapp/src/core/config.py` (add `chat_deployment_mini`, `chat_deployment`)
- Tox env: new `eval` env in `service_webapp/pyproject.toml`
- Justfile: new `eval` recipe in `service_webapp/justfile`
- No migration, no FastAPI router changes, no frontend changes.

### References

- [Source: epics.md §1.8.2 — Story 5.2 acceptance criteria]
- [Source: architecture.md:98 — LLM Provider: Azure OpenAI, GPT-5.4-mini / GPT-5.4]
- [Source: architecture.md:FR-73, FR-74 — LLM-as-Judge and DeepEval requirements]
- [Source: architecture.md:NFR-11 — LLM-as-Judge ≥ 80% pass rate]
- [Source: architecture.md:NFR-12 — Hallucination < 5%]
- [Source: memory: app_code_toolchain — tox per-env-deps discipline]
- [Source: memory: app_code_toolchain — slow test pattern with rootless podman]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
