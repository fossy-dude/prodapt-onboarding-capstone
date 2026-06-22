"""Unit tests for MilvusAdapter + EmbeddingClient (Story 2.7; AC #2, #3, #7)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── MilvusAdapter unit tests ──────────────────────────────────────────────────

@pytest.fixture
def mock_milvus_client() -> MagicMock:
    client = MagicMock()
    client.list_collections.return_value = []
    client.has_collection.return_value = False
    return client


@pytest.fixture
def adapter(mock_milvus_client: MagicMock):
    """Adapter with MilvusClient patched for the entire test lifetime (yield inside with)."""
    with patch("adapters.milvus.MilvusClient") as mock_cls:
        mock_cls.return_value = mock_milvus_client
        mock_cls.create_schema.return_value = MagicMock()
        mock_cls.prepare_index_params.return_value = MagicMock()
        from adapters.milvus import MilvusAdapter

        adp = MilvusAdapter("/tmp/test.db")
        yield adp


async def test_ping_returns_true_when_list_collections_succeeds(
    adapter: object, mock_milvus_client: MagicMock
) -> None:
    mock_milvus_client.list_collections.return_value = []
    result = await adapter.ping()
    assert result is True


async def test_ping_returns_false_when_list_collections_raises(
    adapter: object, mock_milvus_client: MagicMock
) -> None:
    mock_milvus_client.list_collections.side_effect = RuntimeError("connection refused")
    result = await adapter.ping()
    assert result is False


async def test_ping_never_raises(adapter: object, mock_milvus_client: MagicMock) -> None:
    mock_milvus_client.list_collections.side_effect = Exception("unexpected error")
    result = await adapter.ping()
    assert isinstance(result, bool)


async def test_create_collections_if_absent_creates_missing(
    adapter: object, mock_milvus_client: MagicMock
) -> None:
    mock_milvus_client.has_collection.return_value = False
    await adapter.create_collections_if_absent()
    assert mock_milvus_client.create_collection.call_count == 3


async def test_create_collections_if_absent_skips_existing(
    adapter: object, mock_milvus_client: MagicMock
) -> None:
    mock_milvus_client.has_collection.return_value = True
    await adapter.create_collections_if_absent()
    mock_milvus_client.create_collection.assert_not_called()


async def test_create_collections_if_absent_creates_only_missing(
    adapter: object, mock_milvus_client: MagicMock
) -> None:
    existing = {"faq_chunks", "plan_vectors"}
    mock_milvus_client.has_collection.side_effect = lambda name: name in existing
    await adapter.create_collections_if_absent()
    assert mock_milvus_client.create_collection.call_count == 1
    call_kwargs = mock_milvus_client.create_collection.call_args
    assert call_kwargs.kwargs["collection_name"] == "sop_chunks"


async def test_create_collection_schema_embedding_dim_1536(adapter: object) -> None:
    """Schema building records an embedding field with dim=1536."""
    from adapters.milvus import _build_schema

    with patch("adapters.milvus.MilvusClient") as mock_cls:
        schema_mock = MagicMock()
        mock_cls.create_schema.return_value = schema_mock
        mock_cls.prepare_index_params.return_value = MagicMock()
        _build_schema("plan_vectors")

    embedding_dim = None
    for call in schema_mock.add_field.call_args_list:
        kw = call.kwargs
        if kw.get("field_name") == "embedding":
            embedding_dim = kw.get("dim")
            break

    assert embedding_dim == 1536


async def test_upsert_calls_client_upsert(adapter: object, mock_milvus_client: MagicMock) -> None:
    rows = [{"plan_id": "abc", "text": "test", "embedding": [0.0] * 1536}]
    await adapter.upsert("plan_vectors", rows)
    mock_milvus_client.upsert.assert_called_once_with(collection_name="plan_vectors", data=rows)


async def test_close_is_best_effort(adapter: object, mock_milvus_client: MagicMock) -> None:
    mock_milvus_client.close.side_effect = RuntimeError("already closed")
    await adapter.close()


# ── Seeder unit tests ─────────────────────────────────────────────────────────

def test_faq_yaml_has_min_50_entries() -> None:
    from pathlib import Path

    import yaml

    faq_path = Path(__file__).resolve().parents[2] / "data" / "faq.yaml"
    with faq_path.open() as f:
        data = yaml.safe_load(f)
    assert len(data["faqs"]) >= 50


def test_faq_yaml_required_fields_present() -> None:
    from pathlib import Path

    import yaml

    faq_path = Path(__file__).resolve().parents[2] / "data" / "faq.yaml"
    with faq_path.open() as f:
        data = yaml.safe_load(f)
    for entry in data["faqs"]:
        assert "id" in entry
        assert "question" in entry
        assert "answer" in entry
        assert "category" in entry
        assert "source_doc" in entry


# ── EmbeddingClient protocol tests ────────────────────────────────────────────

async def test_azure_embedding_client_uses_langchain() -> None:
    with patch("adapters.embeddings.AzureOpenAIEmbeddings") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.embed_documents.return_value = [[0.1] * 1536, [0.2] * 1536]
        mock_cls.return_value = mock_instance

        from adapters.embeddings import AzureEmbeddingClient

        client = AzureEmbeddingClient(
            azure_endpoint="https://dummy.openai.azure.com/",
            api_key="dummy-key",
            azure_deployment="text-embedding-3-small",
            api_version="2024-08-01-preview",
            dimensions=1536,
        )
        vectors = await client.embed_batch(["hello", "world"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 1536


async def test_embedding_client_batches_correctly() -> None:
    with patch("adapters.embeddings.AzureOpenAIEmbeddings") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.embed_documents.side_effect = lambda texts: [[0.0] * 1536 for _ in texts]
        mock_cls.return_value = mock_instance

        from adapters.embeddings import AzureEmbeddingClient

        client = AzureEmbeddingClient(
            azure_endpoint="https://dummy.openai.azure.com/",
            api_key="dummy-key",
            azure_deployment="text-embedding-3-small",
            api_version="2024-08-01-preview",
            dimensions=1536,
        )
        texts = [f"text {i}" for i in range(250)]
        vectors = await client.embed_batch(texts, batch_size=100)

    assert len(vectors) == 250
    assert mock_instance.embed_documents.call_count == 3
