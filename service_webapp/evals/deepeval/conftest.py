"""DeepEval sub-suite guard (Story 5.2, Task 3).

Skips every DeepEval test when Azure OpenAI is not configured. DeepEval >= 2.0
auto-configures from the ``AZURE_OPENAI_*`` env vars (do NOT instantiate a model
manually — see Dev Notes). The parent ``evals/conftest.py`` already applies the
same guard to the whole evals tree; this restates it for the deepeval/ subtree
per the story spec.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        skip = pytest.mark.skip(reason="Azure OpenAI not configured (set AZURE_OPENAI_API_KEY)")
        for item in items:
            item.add_marker(skip)
