"""LLM-as-Judge eval run over the golden fixture set (Story 5.2; FR-73, NFR-11).

Runs the stub ``graph_callable`` over every golden Q&A pair, judges each answer
with :class:`ResponseQualityJudge`, writes the aggregate report to
``evals/reports/latest.json`` and asserts the NFR-11 >= 80% pass-rate gate.

``@pytest.mark.slow`` + the Azure guard in ``evals/conftest.py`` keep it out of
``just test`` and out of any environment lacking Azure OpenAI keys. It runs only
under ``just eval``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.judges.response_quality import EVAL_PASS_RATE, ResponseQualityJudge, run_judge_evaluation

REPORTS_DIR = Path(__file__).parent / "reports"


@pytest.mark.slow
def test_judge_pass_rate_meets_threshold(
    golden_fixtures: list[dict],
    stub_graph_callable,
) -> None:
    """Judge every golden answer; pass rate must be >= 80% (NFR-11)."""
    # ``openai`` is an eval-env-only dep; import lazily so the module collects in
    # the lean ``test`` env too.
    from openai import AzureOpenAI

    from core.config import settings

    client = AzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    judge = ResponseQualityJudge(client, settings.chat_deployment_mini)

    report = run_judge_evaluation(stub_graph_callable, golden_fixtures, judge)
    report.write(REPORTS_DIR / "latest.json")

    assert report.pass_rate >= EVAL_PASS_RATE, (
        f"LLM-as-Judge pass rate {report.pass_rate:.0%} below {EVAL_PASS_RATE:.0%} gate (NFR-11)"
    )
