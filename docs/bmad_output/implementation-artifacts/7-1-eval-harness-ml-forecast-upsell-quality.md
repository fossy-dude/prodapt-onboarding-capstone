---
baseline_commit: dd7e3df
---

# Story 7.1: Eval Harness — ML Forecast & Upsell Quality

Status: ready-for-dev

## Story

As a **QA engineer**,
I want evaluation harnesses for the ML forecasting model and LLM upsell strategy agent before any implementation,
so that accuracy and quality targets are enforced from the first story.

## Acceptance Criteria

1. **Given** the ops eval harness is set up, **When** `just eval-ops` runs the eval suite, **Then** a ML forecast evaluator loads a fixture CSV of 6-month historical activation data and asserts that the trained scikit-learn model achieves MAPE < 15% on a 3-month holdout set. [Source: epics.md:1954; NFR-14]

2. **And** a LLM-as-Judge evaluator for upsell strategy text asserts: strategy is specific to the segment (not generic), actionable (contains at least one concrete offer), and appropriately scoped (no hallucinated product names). [Source: epics.md:1956; FR-73]

3. **And** both evaluators return structured pass/fail results and CI fails if targets are not met. [Source: epics.md:1958]

4. **And** fixture files are stored in `service_webapp/evals/fixtures/`: `forecast_historical.csv`, `upsell_golden_segments.json`. [Source: epics.md:1960]

5. **And** the ML forecast harness uses scikit-learn for time-series modeling (linear regression or gradient boosting) and provides a reusable evaluation function. [Source: architecture.md:108; technology stack ML Forecasting]

6. **And** the upsell strategy evaluator validates textual output for actionability, specificity, and scope constraints using GPT-5.4-mini as judge. [Source: architecture.md:98; Azure OpenAI]

7. **And** all eval tests are marked `@pytest.mark.slow` and skipped in `just test` — they run only via `just eval-ops`. [Source: memory: app_code_toolchain; slow test pattern]

## Tasks / Subtasks

- [ ] **Task 1: Create ops eval package structure** (AC: #1–#4)
  - [ ] Create directory tree (sibling of existing chatbot/fraud evals — NOT inside `src/`):
    ```
    service_webapp/evals/ops/
    ├── __init__.py
    ├── conftest.py
    ├── test_forecast_accuracy.py
    ├── test_upsell_strategy_quality.py
    ├── forecast_evaluator.py
    ├── upsell_judge.py
    └── fixtures/
        ├── forecast_historical.csv
        └── upsell_golden_segments.json
    ```
  - [ ] `evals/ops/__init__.py` empty.
  - [ ] `evals/ops/conftest.py`: skip ALL tests in this dir if `AZURE_OPENAI_API_KEY == ""` with `pytest.skip("Azure OpenAI not configured")`; provide `forecast_fixtures` fixture (loads CSV) and `upsell_fixtures` fixture (loads JSON).

- [ ] **Task 2: ML forecast fixture dataset** (AC: #1, #4)
  - [ ] Create `service_webapp/evals/ops/fixtures/forecast_historical.csv` with 6 months of synthetic daily activation data (180 rows).
  - [ ] CSV schema: `date,activations,churn,plan_id,price_paise`. Use realistic Indian telecom patterns: weekday/weekend cycles, seasonal trends, gradual growth baseline.
  - [ ] Ensure sufficient signal for ML training: include trend, seasonality, and some noise (but not excessive).
  - [ ] All data synthetic — no real subscriber data or PII.

- [ ] **Task 3: Upsell strategy golden fixtures** (AC: #2, #4)
  - [ ] Create `service_webapp/evals/ops/fixtures/upsell_golden_segments.json` with 20 segment entries.
  - [ ] JSON schema per entry:
    ```json
    {
      "id": "upsell-001",
      "segment_label": "Heavy data user, plan-loyal, low churn risk",
      "kpi_profile": {
        "data_gb_30d": 12.5,
        "plan_price_paise": 29900,
        "recharge_frequency_90d": 3,
        "churn_probability": 0.15
      },
      "expected_strategy_components": ["upgrade_offer", "data_bonus"],
      "expected_plan_references": ["PLAN_A", "PLAN_B"],
      "tags": ["data_heavy", "upsell_candidate"]
    }
    ```
  - [ ] 20 entries covering: data-heavy users (5), voice-heavy users (4), budget-sensitive (4), high-value low-churn (4), borderline cases (3).
  - [ ] All plan references synthetic — no real plan names from the database.

- [ ] **Task 4: ML forecast evaluator** (AC: #1, #3, #5)
  - [ ] Create `service_webapp/evals/ops/forecast_evaluator.py`.
  - [ ] Define the forecast model contract:
    ```python
    ForecastModelCallable = Callable[[pd.DataFrame], "ForecastResult"]
    ```
  - [ ] `ForecastResult` dataclass:
    ```python
    @dataclass
    class ForecastResult:
        predictions: np.ndarray      # 90-day forecast
        lower_bound: np.ndarray     # 95% CI
        upper_bound: np.ndarray     # 95% CI
        mape: float                 # Mean Absolute Percentage Error
    ```
  - [ ] `run_forecast_evaluation(model_callable, train_data, test_data, horizon_days=90) -> ForecastEvalReport` where:
    ```python
    @dataclass
    class ForecastEvalReport:
        mape: float
        pass_threshold: float = 0.15  # 15% MAPE target
        passed: bool
        predictions: np.ndarray
        actuals: np.ndarray
    ```
  - [ ] Include a stub scikit-learn model for harness self-test: `LinearRegression` or `GradientBoostingRegressor` trained on first 5 months, tested on month 6.
  - [ ] MAPE calculation: `mean(abs((actual - predicted) / actual)) * 100`

- [ ] **Task 5: Upsell strategy judge (LLM-as-Judge)** (AC: #2, #3, #6)
  - [ ] Create `service_webapp/evals/ops/upsell_judge.py`.
  - [ ] Class `UpsellStrategyJudge`:
    - Constructor: `__init__(self, azure_client: AzureOpenAI, deployment: str)` — uses Azure OpenAI client.
    - Method `evaluate(self, segment_label: str, kpi_profile: dict, strategy_text: str, expected_components: list) -> JudgeResult`.
    - `JudgeResult` dataclass: `passed: bool, specificity_score: float, actionability_score: float, scope_score: float, reason: str`.
    - Rubric prompt (system): "You are an evaluation judge for telecom upsell strategies. Score the strategy on: (1) Specificity (0.0–1.0): is it tailored to the segment? (2) Actionability (0.0–1.0): does it contain concrete offers? (3) Scope (0.0–1.0): no hallucinated products. Return JSON: {specificity: float, actionability: float, scope: float, reason: str}."
    - Pass threshold: specificity ≥ 0.7 AND actionability ≥ 0.7 AND scope ≥ 0.8.
  - [ ] Function `run_upsell_evaluation(judge, fixtures) -> UpsellEvalReport` where:
    ```python
    @dataclass
    class UpsellEvalReport:
        total: int
        passed: int
        pass_rate: float
        results: list[JudgeResult]
    ```
  - [ ] Use model: `settings.chat_deployment_mini` (gpt-4o-mini deployment) — cheaper for judge calls. [Source: architecture.md:98]

- [ ] **Task 6: Forecast accuracy test + CI gate** (AC: #1, #3, #7)
  - [ ] Create `service_webapp/evals/ops/test_forecast_accuracy.py`.
  - [ ] Test `test_forecast_mape_meets_nfr14()` (marked `@pytest.mark.slow`):
    - Load `forecast_fixtures` from CSV.
    - Split data: first 150 days (5 months) train, last 30 days (1 month) test (simulating holdout).
    - Train a stub scikit-learn model (`LinearRegression` or `GradientBoostingRegressor`) on train data.
    - Generate 30-day forecast on test data.
    - Assert `mape <= 0.15` (15% MAPE target).
    - Write report to `service_webapp/evals/reports/forecast_latest.json`.
  - [ ] Test `test_forecast_model_callable_contract()`: assert the model callable returns `ForecastResult` with correct fields and shapes.

- [ ] **Task 7: Upsell strategy quality test + CI gate** (AC: #2, #3, #7)
  - [ ] Create `service_webapp/evals/ops/test_upsell_strategy_quality.py`.
  - [ ] Test `test_upsell_strategy_quality_gate()` (marked `@pytest.mark.slow`):
    - Load `upsell_fixtures` from JSON.
    - For each fixture, generate a stub strategy text (or use a real strategy agent if available in future stories).
    - Run `UpsellStrategyJudge.evaluate` for each fixture.
    - Assert overall pass rate ≥ 0.80 (80% strategies meet quality thresholds).
    - Write report to `service_webapp/evals/reports/upsell_latest.json`.
  - [ ] Test `test_upsell_judge_no_hallucinations()`: assert no fixture passes if the strategy contains plan names not in `expected_plan_references` (scope validation).

- [ ] **Task 8: `just eval-ops` recipe and tox env** (AC: #3, #7)
  - [ ] Add `[tool.tox.env.eval-ops]` in `service_webapp/pyproject.toml`:
    - `deps`: same as `test` env PLUS `scikit-learn>=1.0`, `pandas>=2.0`, `deepeval>=2.0`, `openai>=1.0`.
    - `commands`: `python -m pytest service_webapp/evals/ops/ -m slow -v --tb=short`.
    - `setenv`: inherit Azure OpenAI env vars (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `CHAT_DEPLOYMENT_MINI`).
    - `package = "skip"`.
    - `pythonpath`: `["src", "."]` (so `evals.ops` resolves).
  - [ ] Add `eval-ops` recipe to `service_webapp/justfile`:
    ```
    eval-ops:
        cd service_webapp && uvx --with tox-uv tox -e eval-ops
    ```
  - [ ] Add `eval-ops` recipe to root `justfile` delegating to service_webapp.
  - [ ] Do NOT add ops deps to `lint` or `test` envs (quarantine rule). The `evals/ops/` package is outside `src/` so pyrefly skips it; ruff lints it (clean).
  - [ ] Add `scikit-learn` to `lint` env deps only if `forecast_evaluator.py` is imported by non-eval code (it won't be in Story 7.1).

- [ ] **Task 9: Unit tests for evaluators** (AC: #1, #2)
  - [ ] Create `service_webapp/tests/unit/test_forecast_evaluator.py` (NOT slow-marked):
    - Mock `ForecastModelCallable`. Test: perfect predictions → MAPE=0; noisy predictions → MAPE>0; threshold at exactly 0.15 → pass; below 0.15 → fail assert.
  - [ ] Create `service_webapp/tests/unit/test_upsell_strategy_judge.py` (NOT slow-marked):
    - Mock `AzureOpenAI` client. Test: specific+actionable+scoped strategy → `passed=True`; generic strategy → `passed=False`; hallucinated products → `passed=False`.

- [ ] **Task 10: Settings extension** (AC: #6)
  - [ ] Verify `service_webapp/src/core/config.py` has `chat_deployment_mini` (added in Story 5.2; no changes needed if present).
  - [ ] If not present, add: `chat_deployment_mini: str = "gpt-4o-mini"`.

## Dev Notes

### Ops evals/ follows established patterns from 5.2 and 6.1

This story leverages patterns from Story 5.2 (chatbot eval) and Story 6.1 (fraud eval):
- `evals/ops/` is at service_webapp root (alongside `evals/`, not inside `src/`)
- Uses `@pytest.mark.slow` to exclude from `just test` gate
- Dedicated `eval-ops` tox env with isolated deps (`scikit-learn`, `pandas`)
- Stub graph_callable for harness self-test; real model/agent plugs in later

### ML forecasting tech stack

Architecture specifies `scikit-learn` for MVP forecasting. Target State may upgrade to TimesFM/Chronos/Prophet/NeuralForecast — this eval harness is designed to be model-agnostic via the `ForecastModelCallable` contract. [Source: architecture.md:108,135]

### LLM-as-Judge for upsell strategy

Upsell strategy evaluation mirrors Story 5.2's response quality judge:
- Uses GPT-5.4-mini for cost efficiency
- Rubric: specificity (segment-tailored?), actionability (concrete offers?), scope (no hallucinations?)
- Pass threshold: ≥ 70% on all dimensions

### Fixture design principles

- `forecast_historical.csv`: 6 months = 180 days of synthetic data. Include trend (growth), seasonality (monthly cycles), and noise (realistic variance). No PII — aggregate counts only.
- `upsell_golden_segments.json`: 20 synthetic segments. Cover the feature space Story 7.6 (LLM labelling) will produce. No real MSISDN/subscriber IDs — KPI profiles only.

### CI gate behavior

Both evaluators write reports to `evals/reports/` (gitignored). The tox command exits non-zero if:
- Forecast MAPE > 15% (NFR-14)
- Upsell strategy pass rate < 80%

This enforces quality from day one. Stories 7.3 (forecast implementation) and 7.7 (upsell agent) must pass these gates to merge.

### Tox per-env-deps discipline

Per [[app_code_toolchain]]: `scikit-learn`, `pandas`, `deepeval`, `openai` go in `eval-ops` env only. Do NOT add to `lint` or `test` envs. `evals/ops/` is outside `src/` so pyrefly doesn't type-check it. Add `scikit-learn` to `lint` deps only if non-eval code imports it (unlikely in 7.1). [Source: memory: app_code_toolchain]

### Azure OpenAI model names

Architecture says "GPT-5.4-mini" — this is the Azure deployment name. Story 7.1 uses `settings.chat_deployment_mini` (added in 5.2). No changes to `config.py` needed if 5.2 is complete. [Source: architecture.md:98]

### slow test pattern

Per [[app_code_toolchain]]: integration tests marked `slow`+`integration`, skipped by default. Ops eval tests follow this: `@pytest.mark.slow`. The `just eval-ops` tox env explicitly runs `-m slow`. [Source: memory: app_code_toolchain]

### Project Structure Notes

- New files: `service_webapp/evals/ops/` tree (outside `src/`)
- Settings change: `service_webapp/src/core/config.py` (verify `chat_deployment_mini` present; add if missing)
- Tox env: new `eval-ops` env in `service_webapp/pyproject.toml`
- Justfile: new `eval-ops` recipe in `service_webapp/justfile` and root `justfile`
- No migration, no FastAPI router changes, no frontend changes.

### References

- [Source: epics.md §1.10.1 — Story 7.1 acceptance criteria]
- [Source: architecture.md:98 — LLM Provider: Azure OpenAI, GPT-5.4-mini]
- [Source: architecture.md:108 — ML Forecasting: scikit-learn (MVP)]
- [Source: architecture.md:NFR-14 — MAPE < 15% for forecasting]
- [Source: architecture.md:FR-73 — LLM-as-Judge for upsell strategy]
- [Source: memory: app_code_toolchain — tox per-env-deps discipline]
- [Source: memory: app_code_toolchain — slow test pattern]
- [Source: docs/bmad_output/implementation-artifacts/5-2-eval-harness-llm-as-judge-deepeval-scaffolding.md — eval harness patterns]
- [Source: docs/bmad_output/implementation-artifacts/6-1-eval-harness-fraud-detection-agent-accuracy.md — eval harness patterns]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
