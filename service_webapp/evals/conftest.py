"""Shared fixtures and guards for the chatbot eval suite (Story 5.2).

``evals/`` lives outside ``src/``; it imports the app via the project-root
``pythonpath`` (``[tool.pytest.ini_options].pythonpath = ["src", "."]``). The
suite is collected only via ``just eval`` (``pytest evals/``); ``just test``
scopes collection to ``tests/`` so evals never run in the standard gate (AC #7).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "chatbot_golden.json"


def _azure_configured() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_API_KEY"))


def pytest_collection_modifyitems(config, items):
    """Skip every eval test when Azure OpenAI is not configured.

    DeepEval and the LLM-as-Judge both call Azure OpenAI; in CI/dev without keys
    the whole suite is skipped rather than erroring (AC #7 + Dev Notes).
    """
    if not _azure_configured():
        skip = pytest.mark.skip(reason="Azure OpenAI not configured (set AZURE_OPENAI_API_KEY)")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def golden_fixtures() -> list[dict]:
    """Load the 20 golden Q&A pairs from ``evals/fixtures/chatbot_golden.json``."""
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def stub_graph_callable(golden_fixtures: list[dict]) -> Callable[[str, dict], str]:
    """Story 5.2 stub agent: returns the fixture's expected answer for a question.

    Story 5.4+ replaces this with the real ``support_agent_graph.invoke``; the
    ``graph_callable: Callable[[str, dict], str]`` contract is what makes the
    harness reusable across all Epic 5 agent stories (AC #4).
    """
    by_question = {fx["question"]: fx["expected_answer"] for fx in golden_fixtures}

    def _stub(question: str, context: dict) -> str:
        return by_question.get(question, "")

    return _stub
