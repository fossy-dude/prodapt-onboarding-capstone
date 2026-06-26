"""Unit tests for the LLM-as-Judge evaluator with a mocked Azure OpenAI client (AC #1, #4).

The judge calls ``client.chat.completions.create`` and parses the JSON it returns,
so we stub the Azure client with a tiny fake that yields a configurable JSON
verdict. These are unit tests (no real LLM, not ``@pytest.mark.slow``) and run in
the standard ``just test`` gate.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from evals.judges.response_quality import (
    PASS_THRESHOLD,
    EvalReport,
    JudgeResult,
    ResponseQualityJudge,
    run_judge_evaluation,
)

FIXTURES = [
    {
        "id": "balance-001",
        "category": "balance",
        "question": "What is my current balance?",
        "context": "Subscriber MSISDN[-4:] 1234 has balance 5000 paise (Rs 50.00).",
        "expected_answer": "Your current balance is Rs 50.00.",
        "tags": ["balance", "inquiry"],
    },
    {
        "id": "plan-001",
        "category": "plan",
        "question": "What are the details of my current plan?",
        "context": "Plan 'Daily Saver' costs Rs 29 and includes 2.0 GB daily data.",
        "expected_answer": "Your plan 'Daily Saver' costs Rs 29 with 2.0 GB daily data.",
        "tags": ["plan", "details"],
    },
]


class FakeCompletions:
    """Mimics ``AzureOpenAI().chat.completions`` returning scripted JSON verdicts."""

    def __init__(self, verdicts: list[dict[str, Any]]) -> None:
        self._verdicts = list(verdicts)
        self._calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs)
        verdict = self._verdicts.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(verdict)))])


class FakeAzureClient:
    """Minimal stand-in for ``openai.AzureOpenAI`` exposing ``.chat.completions``."""

    def __init__(self, verdicts: list[dict[str, Any]]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(verdicts))


def test_relevant_and_accurate_answer_passes() -> None:
    """Both rubrics above threshold -> passed=True and scores echoed back."""
    judge = ResponseQualityJudge(FakeAzureClient([{"relevance": 0.95, "accuracy": 0.9, "reason": "ok"}]), "gpt-4o-mini")
    result = judge.evaluate("Q", "relevant accurate answer", "ctx")

    assert isinstance(result, JudgeResult)
    assert result.passed is True
    assert result.relevance_score == 0.95
    assert result.accuracy_score == 0.9
    assert result.reason == "ok"


def test_irrelevant_answer_fails() -> None:
    """Relevance below threshold -> passed=False even if accuracy is high."""
    judge = ResponseQualityJudge(
        FakeAzureClient([{"relevance": 0.2, "accuracy": 0.9, "reason": "off-topic"}]), "gpt-4o-mini"
    )
    result = judge.evaluate("Q", "totally unrelated", "ctx")

    assert result.passed is False
    assert result.relevance_score < PASS_THRESHOLD


def test_inaccurate_answer_fails() -> None:
    """Accuracy below threshold -> passed=False even if relevance is high."""
    judge = ResponseQualityJudge(
        FakeAzureClient([{"relevance": 0.9, "accuracy": 0.3, "reason": "contradicts context"}]),
        "gpt-4o-mini",
    )
    result = judge.evaluate("Q", "plausible but wrong", "ctx")

    assert result.passed is False
    assert result.accuracy_score < PASS_THRESHOLD


def test_boundary_threshold_passes() -> None:
    """A score exactly at the threshold counts as a pass (>= comparison)."""
    judge = ResponseQualityJudge(
        FakeAzureClient([{"relevance": PASS_THRESHOLD, "accuracy": PASS_THRESHOLD, "reason": "edge"}]),
        "gpt-4o-mini",
    )
    result = judge.evaluate("Q", "edge answer", "ctx")
    assert result.passed is True


def test_judge_uses_mini_deployment_and_json_mode() -> None:
    """The judge calls the configured deployment and requests JSON output."""
    fake = FakeAzureClient([{"relevance": 0.9, "accuracy": 0.9, "reason": "ok"}])
    ResponseQualityJudge(fake, "my-deploy").evaluate("Q", "A", "C")

    call = fake.chat.completions._calls[0]
    assert call["model"] == "my-deploy"
    assert call["response_format"] == {"type": "json_object"}
    assert any(m["role"] == "system" for m in call["messages"])
    assert any(m["role"] == "user" and "Question: Q" in m["content"] for m in call["messages"])


def test_run_judge_evaluation_aggregates_pass_rate() -> None:
    """The harness runs the graph callable per fixture and aggregates the pass rate."""
    # Two passes -> 100% pass rate.
    verdicts = [{"relevance": 0.9, "accuracy": 0.9, "reason": "ok"} for _ in FIXTURES]
    judge = ResponseQualityJudge(FakeAzureClient(verdicts), "gpt-4o-mini")
    stub = lambda question, context: f"answer to {question}"

    report = run_judge_evaluation(stub, FIXTURES, judge)

    assert isinstance(report, EvalReport)
    assert report.total == len(FIXTURES)
    assert report.passed == len(FIXTURES)
    assert report.pass_rate == 1.0
    assert len(report.results) == len(FIXTURES)


def test_run_judge_evaluation_partial_pass_rate() -> None:
    """Mixed verdicts yield the correct fractional pass rate."""
    verdicts = [
        {"relevance": 0.9, "accuracy": 0.9, "reason": "ok"},
        {"relevance": 0.2, "accuracy": 0.9, "reason": "off-topic"},
    ]
    judge = ResponseQualityJudge(FakeAzureClient(verdicts), "gpt-4o-mini")
    stub = lambda question, context: "answer"

    report = run_judge_evaluation(stub, FIXTURES, judge)

    assert report.total == 2
    assert report.passed == 1
    assert report.pass_rate == 0.5


def test_eval_report_serialises_and_writes(tmp_path) -> None:
    """EvalReport.to_dict / write round-trip to a JSON report file."""
    report = EvalReport(
        total=1,
        passed=1,
        pass_rate=1.0,
        results=[
            JudgeResult("Q", "A", True, 0.9, 0.9, "ok"),
        ],
    )

    out = report.write(tmp_path / "reports" / "latest.json")
    assert out.exists()
    import json as _json

    payload = _json.loads(out.read_text())
    assert payload["total"] == 1
    assert payload["passed"] == 1
    assert payload["pass_rate"] == 1.0
    assert payload["results"][0]["question"] == "Q"
    assert payload["results"][0]["passed"] is True
