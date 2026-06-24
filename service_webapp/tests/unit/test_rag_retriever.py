"""Unit tests for the hybrid RAG retriever (Story 5.3; AC #1–#5).

The Azure OpenAI client and the pymilvus ``MilvusClient`` are mocked so the RRF
fusion logic is exercised deterministically without network or Milvus Lite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.rag.retriever import HybridRetriever, RagChunk


def _hit(chunk_id: str, text: str, **metadata: object) -> dict:
    """Build a pymilvus-shaped search hit (pk in ``id``, fields in ``entity``)."""
    return {"id": chunk_id, "entity": {"text": text, **metadata}}


@pytest.fixture
def azure_mock() -> MagicMock:
    """Fake AzureOpenAI: embeddings.create → one 1536-dim vector."""
    client = MagicMock()
    client.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
    return client


@pytest.fixture
def milvus_search_mock(azure_mock: MagicMock):
    """Patch MilvusClient and yield the ``search`` mock for per-test wiring."""
    with patch("agents.rag.retriever.MilvusClient") as mock_cls:
        search_mock = MagicMock()
        mock_cls.return_value.search = search_mock
        yield search_mock


def _build(azure_mock: MagicMock, langfuse: MagicMock | None = None) -> HybridRetriever:
    return HybridRetriever(
        milvus_uri="./data/milvus/sboai.db",
        azure_client=azure_mock,
        embedding_deployment="text-embedding-3-small",
        langfuse_client=langfuse,
    )


async def test_embed_calls_azure_and_returns_1536_dim_vector(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    retriever = _build(azure_mock)
    vec = await retriever.embed("hello")
    azure_mock.embeddings.create.assert_called_once_with(model="text-embedding-3-small", input="hello")
    assert len(vec) == 1536


async def test_search_returns_chunks_sorted_by_rrf_desc(azure_mock: MagicMock, milvus_search_mock: MagicMock) -> None:
    # Call order: faq dense, faq sparse, plan dense, plan sparse.
    # A and B both appear at the top of BOTH faq lists (strong agreement → survive
    # the 0.03 threshold). D appears rank-1 dense / rank-2 sparse on plan_vectors.
    # X appears in only one list → below threshold, dropped.
    milvus_search_mock.side_effect = [
        [_hit("A", "a text"), _hit("B", "b text")],  # faq dense
        [_hit("A", "a text"), _hit("B", "b text")],  # faq sparse
        [_hit("D", "d text", plan_type="unlimited")],  # plan dense
        [_hit("X", "x text"), _hit("D", "d text")],  # plan sparse
    ]
    retriever = _build(azure_mock)

    results = await retriever.search("what is my balance?", top_k=3)

    assert len(results) == 3
    assert [r.chunk_id for r in results] == ["A", "D", "B"]
    # RRF scores strictly non-increasing.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(r.score >= 0.03 for r in results)
    assert all(isinstance(r, RagChunk) for r in results)


async def test_search_respects_top_k(azure_mock: MagicMock, milvus_search_mock: MagicMock) -> None:
    milvus_search_mock.side_effect = [
        [_hit("A", "a"), _hit("B", "b"), _hit("C", "c")],  # faq dense
        [_hit("A", "a"), _hit("B", "b"), _hit("C", "c")],  # faq sparse
        [],  # plan dense
        [],  # plan sparse
    ]
    retriever = _build(azure_mock)

    results = await retriever.search("query", top_k=2)

    assert len(results) == 2


async def test_search_returns_empty_when_all_below_threshold(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    # Each chunk appears in only ONE list → RRF ≈ 1/61 ≈ 0.016 < 0.03 → dropped.
    milvus_search_mock.side_effect = [
        [_hit("A", "a text")],  # faq dense
        [],  # faq sparse
        [_hit("D", "d text")],  # plan dense
        [],  # plan sparse
    ]
    retriever = _build(azure_mock)

    results = await retriever.search("obscure query")

    assert results == []
    # AC #5: Azure was still called (embedding happened) even with no matches.
    azure_mock.embeddings.create.assert_called_once()


async def test_search_populates_metadata_from_scalar_fields(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    milvus_search_mock.side_effect = [
        [_hit("A", "a text", category="billing", source_doc="faq.yaml", plan_type="prepaid")],  # faq dense
        [_hit("A", "a text", category="billing", source_doc="faq.yaml", plan_type="prepaid")],  # faq sparse
        [],  # plan dense
        [],  # plan sparse
    ]
    retriever = _build(azure_mock)

    results = await retriever.search("billing query")

    assert len(results) == 1
    chunk = results[0]
    assert chunk.collection == "faq_chunks"
    assert chunk.metadata["category"] == "billing"
    assert chunk.metadata["source_doc"] == "faq.yaml"


async def test_search_uses_correct_anns_fields_and_collections(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    milvus_search_mock.side_effect = [[], [], [], []]
    retriever = _build(azure_mock)

    await retriever.search("query", top_k=3)

    calls = milvus_search_mock.call_args_list
    assert len(calls) == 4
    collections = [c.kwargs["collection_name"] for c in calls]
    assert collections.count("faq_chunks") == 2
    assert collections.count("plan_vectors") == 2
    anns_fields = {c.kwargs["anns_field"] for c in calls}
    assert anns_fields == {"embedding", "sparse_embedding"}
    # Sparse search passes raw query text (native BM25 analyzer), dense passes vector.
    dense_call = next(c for c in calls if c.kwargs["anns_field"] == "embedding")
    assert len(dense_call.kwargs["data"][0]) == 1536
    sparse_call = next(c for c in calls if c.kwargs["anns_field"] == "sparse_embedding")
    assert sparse_call.kwargs["data"] == ["query"]


async def test_search_records_langfuse_span_with_correct_shape(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    langfuse = MagicMock()
    observation = MagicMock()
    observation_cm = MagicMock()
    observation_cm.__enter__.return_value = observation
    langfuse.start_as_current_observation.return_value = observation_cm

    milvus_search_mock.side_effect = [
        [_hit("A", "a text")],  # faq dense
        [_hit("A", "a text")],  # faq sparse  → A survives threshold
        [],  # plan dense
        [],  # plan sparse
    ]
    retriever = _build(azure_mock, langfuse=langfuse)

    results = await retriever.search("what is my balance?")

    langfuse.start_as_current_observation.assert_called_once()
    kwargs = langfuse.start_as_current_observation.call_args.kwargs
    assert kwargs["name"] == "rag_retrieval"
    assert kwargs["as_type"] == "span"
    assert kwargs["input"] == {"query": "what is my balance?"}  # no MSISDN/PII

    observation.update.assert_called_once()
    out = observation.update.call_args.kwargs["output"]
    assert out["chunks"] == [r.chunk_id for r in results]
    assert out["rrf_scores"] == [r.score for r in results]
    observation_cm.__exit__.assert_called_once()


async def test_search_without_langfuse_does_not_touch_observability(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    milvus_search_mock.side_effect = [[_hit("A", "a")], [_hit("A", "a")], [], []]
    retriever = _build(azure_mock, langfuse=None)  # disabled path

    results = await retriever.search("query")

    assert len(results) == 1  # still works, no client constructed


async def test_search_falls_back_when_langfuse_span_open_fails(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    langfuse = MagicMock()
    langfuse.start_as_current_observation.side_effect = RuntimeError("langfuse down")
    milvus_search_mock.side_effect = [[_hit("A", "a")], [_hit("A", "a")], [], []]
    retriever = _build(azure_mock, langfuse=langfuse)

    results = await retriever.search("query")  # must not raise

    assert len(results) == 1


async def test_dense_and_sparse_search_tolerate_empty_results(
    azure_mock: MagicMock, milvus_search_mock: MagicMock
) -> None:
    milvus_search_mock.return_value = []  # no query-results list at all
    retriever = _build(azure_mock)

    results = await retriever.search("query")

    assert results == []
