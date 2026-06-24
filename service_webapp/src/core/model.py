"""Azure OpenAI model abstraction (Story 5.2 code review fix).

Provides a centralized ``get_model`` function that returns configured Azure
OpenAI model instances based on complexity requirements. This abstraction:

* Eliminates manual AzureOpenAIModel instantiation across the codebase
* Supports dual deployment strategy: fast (mini) vs perf (default)
* Shared between src/ and evals/ for consistency

The function returns ``deepeval.models.llms.azure_model.AzureOpenAIModel``
instances configured from ``core.config.settings``.
"""

from __future__ import annotations

from enum import Enum

from deepeval.models.llms.azure_model import AzureOpenAIModel

from core.config import settings


class ModelComplexity(Enum):
    """Model deployment selection by performance profile.

    * FAST: Use the cheaper, faster deployment (mini model) for judge/eval calls
    * PERF: Use the primary agent deployment for production workloads
    """

    FAST = "fast"
    PERF = "perf"


def get_model(complexity: ModelComplexity = ModelComplexity.PERF) -> AzureOpenAIModel:
    """Return a configured Azure OpenAI model instance.

    Args:
        complexity: Performance profile selector. Default is PERF.

    Returns
    -------
        AzureOpenAIModel: Configured model instance ready for use with DeepEval
        metrics or other Azure OpenAI integrations.

    Example:
        >>> from core.model import get_model, ModelComplexity
        >>> # For eval/judge calls (cheaper, faster)
        >>> judge_model = get_model(ModelComplexity.FAST)
        >>> # For production agent calls
        >>> agent_model = get_model(ModelComplexity.PERF)
    """
    if complexity == ModelComplexity.FAST:
        deployment_name = settings.chat_deployment_mini
        model = settings.chat_deployment_mini
    else:
        deployment_name = settings.chat_deployment
        model = settings.chat_deployment

    return AzureOpenAIModel(
        model=model,
        deployment_name=deployment_name,
        api_key=settings.azure_openai_api_key,
        base_url=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
