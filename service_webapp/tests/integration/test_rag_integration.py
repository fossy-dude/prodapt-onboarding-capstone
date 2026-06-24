"""Slow integration test for the hybrid RAG retriever (Story 5.3; AC #1-#5).

Requires a live Milvus Lite DB (seeded by Story 2.7) AND configured Azure
OpenAI embeddings. Skipped unless ``--run-slow`` is passed AND the Milvus DB
file exists AND an Azure endpoint/key is set — so the standard ``just test`` gate
never attempts real network or missing-file access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import settings


@pytest.mark.slow
@pytest.mark.integration
async def test_rag_search_returns_grounded_chunks_or_empty() -> None:
    if not Path(settings.milvus_db_uri).exists():
        pytest.skip(f"no seeded Milvus Lite DB at {settings.milvus_db_uri}")
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        pytest.skip("Azure OpenAI not configured")

    from openai import AzureOpenAI

    from agents.rag.retriever import HybridRetriever

    azure_client = AzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    retriever = HybridRetriever(
        milvus_uri=settings.milvus_db_uri,
        azure_client=azure_client,
        embedding_deployment=settings.embedding_model,
    )
    try:
        results = await retriever.search("how do I recharge my plan?", top_k=3)
    finally:
        await retriever.close()

    # Either grounded chunks (<=3, each a RagChunk with score >= 0.03) or an empty
    # list (no relevant chunk) — both are valid outcomes per AC #3/#5.
    assert len(results) <= 3
    assert all(r.score >= 0.03 for r in results)
