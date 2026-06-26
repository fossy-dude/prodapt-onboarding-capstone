"""DeepEval sub-suite guard and fixtures (Story 5.2, Task 3).

Skips every DeepEval test when Azure OpenAI is not configured. The
``deepeval_judge_model`` fixture uses the centralized ``get_model`` abstraction
from ``core.model`` which returns configured AzureOpenAIModel instances.

The parent ``evals/conftest.py`` already applies the same guard to the whole evals
tree; this restates it for the deepeval/ subtree per the story spec.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        skip = pytest.mark.skip(reason="Azure OpenAI not configured (set AZURE_OPENAI_API_KEY)")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def deepeval_judge_model():
    from core.model import ModelComplexity, get_model

    return get_model(ModelComplexity.FAST)
