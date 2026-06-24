"""DeepEval quality metrics over the golden fixture set (Story 5.2; FR-74, NFR-12).

DeepEval auto-configures Azure OpenAI from the ``AZURE_OPENAI_*`` env vars.
All tests are ``@pytest.mark.slow`` and run ONLY under ``just eval``
(``pytest evals/``); they are skipped in ``just test`` and when Azure keys are
absent (see ``conftest.py``).

Story 5.2 has no real agent yet, so the agent output under test is the fixture's
``expected_answer`` via the stub graph callable (the same harness contract the
real LangGraph agent plugs into in Story 5.4). DeepEval imports are deferred into
the test bodies so this module imports cleanly in the lean ``test``/``lint`` envs
where ``deepeval`` is not installed.
"""

from __future__ import annotations

import pytest

# Faithfulness / Answer-Relevancy gate (NFR-11) and Hallucination gate (NFR-12).
FAITHFULNESS_THRESHOLD = 0.8
RELEVANCY_THRESHOLD = 0.8
HALLUCINATION_MAX = 0.05


@pytest.mark.slow
def test_faithfulness_on_golden_fixtures(golden_fixtures: list[dict]) -> None:
    """Each golden answer must be faithful AND relevant to its question/context.

    ``FaithfulnessMetric`` checks the answer is entailed by ``retrieval_context``;
    ``AnswerRelevancyMetric`` checks it addresses the ``input``. Both must clear
    their 0.8 thresholds on every fixture.
    """
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    faithfulness = FaithfulnessMetric(threshold=FAITHFULNESS_THRESHOLD)
    relevancy = AnswerRelevancyMetric(threshold=RELEVANCY_THRESHOLD)

    faith_scores: list[float] = []
    rel_scores: list[float] = []
    for fx in golden_fixtures:
        test_case = LLMTestCase(
            input=fx["question"],
            actual_output=fx["expected_answer"],
            retrieval_context=[fx["context"]],
        )
        faithfulness.measure(test_case)
        relevancy.measure(test_case)
        faith_scores.append(faithfulness.score)
        rel_scores.append(relevancy.score)

    assert min(faith_scores) >= FAITHFULNESS_THRESHOLD, f"Faithfulness below threshold: min={min(faith_scores)}"
    assert min(rel_scores) >= RELEVANCY_THRESHOLD, f"Answer relevancy below threshold: min={min(rel_scores)}"


@pytest.mark.slow
def test_hallucination_below_threshold(golden_fixtures: list[dict]) -> None:
    """No golden answer may hallucinate beyond the 5% gate (NFR-12).

    ``HallucinationMetric`` scores contradiction with ``context`` (higher = more
    hallucination); the max score across the fixture set must stay under 0.05.
    """
    from deepeval.metrics import HallucinationMetric
    from deepeval.test_case import LLMTestCase

    metric = HallucinationMetric(threshold=HALLUCINATION_MAX)
    scores: list[float] = []
    for fx in golden_fixtures:
        test_case = LLMTestCase(
            input=fx["question"],
            actual_output=fx["expected_answer"],
            context=[fx["context"]],
        )
        metric.measure(test_case)
        scores.append(metric.score)

    assert max(scores) < HALLUCINATION_MAX, f"Hallucination above gate: max={max(scores)}"
