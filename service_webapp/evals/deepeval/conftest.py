"""DeepEval sub-suite guard and fixtures (Story 5.2, Task 3).

Skips every DeepEval test when Azure OpenAI is not configured. DeepEval does NOT
auto-configure from env vars — callers must pass an explicit model to each metric.
The ``deepeval_judge_model`` fixture below constructs ``AzureOpenAIModel`` from
``core.config.settings`` and is injected into every metric instantiation.

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
    from deepeval.models.llms.azure_model import AzureOpenAIModel

    from core.config import settings

    return AzureOpenAIModel(
        model=settings.chat_deployment_mini,
        deployment_name=settings.chat_deployment_mini,
        api_key=settings.azure_openai_api_key,
        base_url=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
