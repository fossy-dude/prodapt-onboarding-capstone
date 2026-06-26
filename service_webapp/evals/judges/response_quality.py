"""LLM-as-Judge evaluator for chatbot response quality (Story 5.2; FR-73, NFR-11).

Grades agent answers against golden context on two rubrics -- *relevance* (does
the answer address the question?) and *factual accuracy* (is it consistent with
the knowledge base context?) -- using an Azure OpenAI deployment as the judge.

The harness is reusable across every Epic 5 agent story: :func:`run_judge_evaluation`
accepts any ``graph_callable: Callable[[str, dict], str]`` and a fixture set, so
Story 5.2 validates the harness against a stub while Story 5.4+ wires in the real
LangGraph support agent (``support_agent_graph.invoke``) as a regression gate.

The Azure OpenAI client (``openai.AzureOpenAI``) is imported lazily inside
:meth:`ResponseQualityJudge.evaluate` so this module stays importable in the lean
``test``/``lint`` environments where the ``openai`` package is not installed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-only imports, kept out of runtime deps
    from collections.abc import Callable

    from openai import AzureOpenAI

logger = logging.getLogger(__name__)

#: Minimum score (0.0-1.0) a rubric must reach for the case to count as a pass.
PASS_THRESHOLD = 0.7

#: Overall LLM-as-Judge pass-rate gate the eval suite must clear (NFR-11).
EVAL_PASS_RATE = 0.8

JUDGE_SYSTEM_PROMPT = (
    "You are an evaluation judge for a telecom billing assistant. "
    "Score the answer on: (1) Relevance (0.0-1.0): does it directly address the question? "
    "(2) Factual accuracy (0.0-1.0): is it consistent with the provided context? "
    'Return JSON: {"relevance": float, "accuracy": float, "reason": str}.'
)


@dataclass
class JudgeResult:
    """Single graded case: the answer given and the judge's verdict."""

    question: str
    answer: str
    passed: bool
    relevance_score: float
    accuracy_score: float
    reason: str


@dataclass
class EvalReport:
    """Aggregate verdict over a fixture set."""

    total: int
    passed: int
    pass_rate: float
    results: list[JudgeResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the report to a JSON-friendly dict (for ``reports/latest.json``)."""
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 4),
            "results": [asdict(r) for r in self.results],
        }

    def write(self, path: str | Path) -> Path:
        """Write the report as pretty JSON to ``path`` (creating parent dirs)."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return out


class ResponseQualityJudge:
    """LLM-as-Judge that scores an answer's relevance and factual accuracy.

    Parameters
    ----------
    azure_client:
        An ``openai.AzureOpenAI`` client. Kept as ``Any`` at runtime (the type is
        only imported under ``TYPE_CHECKING``) so the module imports without the
        ``openai`` package installed.
    deployment:
        The Azure OpenAI *deployment name* (not model name) to call for judging.
        Story 5.2 uses ``settings.chat_deployment_mini`` (a cheaper deployment).
    """

    def __init__(self, azure_client: AzureOpenAI, deployment: str) -> None:
        self._client = azure_client
        self._deployment = deployment

    def evaluate(self, question: str, answer: str, context: str) -> JudgeResult:
        """Grade one ``answer`` for ``question`` against ``context``.

        Returns a :class:`JudgeResult`; ``passed`` is True only when BOTH rubric
        scores meet :data:`PASS_THRESHOLD`.
        """
        user_prompt = f"Question: {question}\nContext: {context}\nAnswer: {answer}\n\nReturn only the JSON object."
        completion = self._client.chat.completions.create(
            model=self._deployment,
            response_format={"type": "json_object"},
            temperature=0.0,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)

        relevance = float(parsed.get("relevance", 0.0))
        accuracy = float(parsed.get("accuracy", 0.0))
        reason = str(parsed.get("reason", ""))
        passed = relevance >= PASS_THRESHOLD and accuracy >= PASS_THRESHOLD
        return JudgeResult(
            question=question,
            answer=answer,
            passed=passed,
            relevance_score=relevance,
            accuracy_score=accuracy,
            reason=reason,
        )


def run_judge_evaluation(
    graph_callable: Callable[[str, dict], str],
    fixtures: list[dict],
    judge: ResponseQualityJudge,
) -> EvalReport:
    """Run ``graph_callable`` over every fixture and judge each answer.

    ``graph_callable`` takes ``(question, context_dict)`` and returns the agent's
    answer string. The fixture's ``context`` (and ``category``) are passed in the
    context dict so the real agent (Story 5.4) can use them as runtime state.

    Returns an :class:`EvalReport` with the per-case results and the overall
    pass rate.
    """
    results: list[JudgeResult] = []
    for fixture in fixtures:
        question = fixture["question"]
        context_dict = {
            "context": fixture["context"],
            "category": fixture.get("category", ""),
        }
        answer = graph_callable(question, context_dict)
        results.append(judge.evaluate(question, answer, fixture["context"]))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    pass_rate = passed / total if total else 0.0
    return EvalReport(total=total, passed=passed, pass_rate=pass_rate, results=results)
