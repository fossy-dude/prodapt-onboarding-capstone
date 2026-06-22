"""Azure OpenAI embedding helper using LangChain (Story 2.7; architecture §1.6.1).

Only LangChain is used for the Azure OpenAI connection and embedding calls.
Texts are embedded in batches (default 100) to stay within Azure rate limits.
The client is injectable/mockable: tests pass a fake instead of hitting the network.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from langchain_openai import AzureOpenAIEmbeddings

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 100


@runtime_checkable
class EmbeddingClientProtocol(Protocol):
    """Thin protocol so the seeder and tests can swap in fakes."""

    async def embed_batch(self, texts: list[str], batch_size: int = _DEFAULT_BATCH_SIZE) -> list[list[float]]:
        """Return one float vector per text in the same order."""
        ...


class AzureEmbeddingClient(EmbeddingClientProtocol):
    """LangChain AzureOpenAIEmbeddings wrapper with manual batching."""

    def __init__(
        self,
        azure_endpoint: str,
        api_key: str,
        azure_deployment: str,
        api_version: str,
        dimensions: int = 1536,
    ) -> None:
        self._model = AzureOpenAIEmbeddings(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            azure_deployment=azure_deployment,
            openai_api_version=api_version,
            dimensions=dimensions,
        )

    async def embed_batch(self, texts: list[str], batch_size: int = _DEFAULT_BATCH_SIZE) -> list[list[float]]:
        """Embed ``texts`` in batches of ``batch_size``; return vectors in order."""
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            vectors = await asyncio.to_thread(self._model.embed_documents, chunk)
            results.extend(vectors)
            logger.debug("Embedded batch %d-%d of %d", i, i + len(chunk), len(texts))
        return results


def make_embedding_client(settings: object) -> AzureEmbeddingClient:
    """Construct an ``AzureEmbeddingClient`` from the config singleton."""
    return AzureEmbeddingClient(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.embedding_model,
        api_version=settings.azure_openai_api_version,
        dimensions=settings.embedding_dimensions,
    )
