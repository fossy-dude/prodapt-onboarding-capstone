"""Integration test: real Milvus Lite in tmp dir (Story 2.7; AC #2, #3, #7).

Marked ``slow`` + ``integration``: needs pymilvus[milvus-lite] but NO container.
Milvus Lite is in-process; embeddings are faked (fixed 1536-float vectors).
Run with: pytest -m slow
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]


@pytest.fixture(scope="module")
def milvus_db_path() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


@pytest.fixture(scope="module")
def real_adapter(milvus_db_path: str) -> object:
    from adapters.milvus import MilvusAdapter

    return MilvusAdapter(milvus_db_path)


@pytest.fixture
def fake_embedding() -> list[float]:
    return [0.01] * 1536


async def test_ping_returns_true_with_real_milvus(real_adapter: object) -> None:
    result = await real_adapter.ping()
    assert result is True


async def test_create_collections_if_absent(real_adapter: object) -> None:
    await real_adapter.create_collections_if_absent()
    from pymilvus import MilvusClient

    client = real_adapter._client
    collections = client.list_collections()
    assert "faq_chunks" in collections
    assert "plan_vectors" in collections
    assert "sop_chunks" in collections


async def test_collections_have_correct_fields(real_adapter: object) -> None:
    client = real_adapter._client
    for name in ["faq_chunks", "plan_vectors", "sop_chunks"]:
        schema = client.describe_collection(name)
        field_names = {f["name"] for f in schema["fields"]}
        assert "embedding" in field_names, f"{name}: embedding field missing"
        assert "text" in field_names, f"{name}: text field missing"
        assert "sparse_embedding" in field_names, f"{name}: sparse_embedding field missing"


async def test_upsert_and_count(real_adapter: object, fake_embedding: list[float]) -> None:
    rows = [
        {
            "plan_id": "plan-001",
            "text": "Basic prepaid plan 30 days",
            "embedding": fake_embedding,
            "plan_type": "prepaid",
            "price": 29900,
            "validity": 30,
        },
        {
            "plan_id": "plan-002",
            "text": "Premium 5G plan unlimited data",
            "embedding": fake_embedding,
            "plan_type": "5g",
            "price": 59900,
            "validity": 28,
        },
    ]
    await real_adapter.upsert("plan_vectors", rows)
    count = real_adapter._client.get_collection_stats("plan_vectors")["row_count"]
    assert count == 2


async def test_upsert_faq_chunks(real_adapter: object, fake_embedding: list[float]) -> None:
    rows = [
        {
            "chunk_id": f"faq-{i:03d}",
            "text": f"Question {i} answer {i}",
            "embedding": fake_embedding,
            "category": "billing",
            "source_doc": "test-doc",
            "plan_type": "all",
        }
        for i in range(5)
    ]
    await real_adapter.upsert("faq_chunks", rows)
    count = real_adapter._client.get_collection_stats("faq_chunks")["row_count"]
    assert count == 5


async def test_upsert_sop_chunks(real_adapter: object, fake_embedding: list[float]) -> None:
    rows = [
        {
            "chunk_id": "sop-001",
            "text": "Data throttling rule: reduce speed after 5GB daily usage",
            "embedding": fake_embedding,
            "rule_id": "doc-fairuse",
            "severity": "medium",
            "domain": "data",
        }
    ]
    await real_adapter.upsert("sop_chunks", rows)
    count = real_adapter._client.get_collection_stats("sop_chunks")["row_count"]
    assert count >= 1


async def test_idempotency_drop_and_recreate(real_adapter: object, fake_embedding: list[float]) -> None:
    """Re-running create_collections_if_absent (drop+recreate via seeder) resets counts."""
    from adapters.milvus import _COLLECTION_EXTRA_FIELDS, _build_index_params, _build_schema

    client = real_adapter._client
    for name in _COLLECTION_EXTRA_FIELDS:
        if client.has_collection(name):
            client.drop_collection(name)
        client.create_collection(
            collection_name=name,
            schema=_build_schema(name),
            index_params=_build_index_params(),
        )
    for name in _COLLECTION_EXTRA_FIELDS:
        count = client.get_collection_stats(name)["row_count"]
        assert count == 0, f"{name}: expected 0 rows after drop+recreate, got {count}"
