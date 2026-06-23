"""Milvus Lite adapter implementing VectorStoreProtocol (Story 2.7; architecture §1.12.1).

pymilvus is synchronous; all blocking calls are wrapped with ``asyncio.to_thread``
so the async Protocol contract is satisfied without blocking the event loop.

Collections use an HNSW index on ``embedding`` (dense) and a BM25-backed
SPARSE_FLOAT_VECTOR field (``sparse_embedding``) for hybrid search readiness.
Requires pymilvus >= 2.5 for the BM25 ``Function`` API (auto-generated sparse field).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker

from core.protocols.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 1536
_MAX_VARCHAR = 65_535

# Per-collection metadata scalar fields (beyond the shared pk / text / embedding trio).
_COLLECTION_EXTRA_FIELDS: dict[str, list[dict[str, Any]]] = {
    "faq_chunks": [
        {"field_name": "category", "datatype": DataType.VARCHAR, "max_length": 256},
        {"field_name": "source_doc", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "plan_type", "datatype": DataType.VARCHAR, "max_length": 128},
    ],
    "plan_vectors": [
        {"field_name": "plan_type", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "price", "datatype": DataType.INT64},
        {"field_name": "validity", "datatype": DataType.INT64},
    ],
    "sop_chunks": [
        {"field_name": "rule_id", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "severity", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "domain", "datatype": DataType.VARCHAR, "max_length": 256},
    ],
}

# Primary key field name per collection (holds the source UUID).
_PK_FIELD: dict[str, str] = {
    "faq_chunks": "chunk_id",
    "plan_vectors": "plan_id",
    "sop_chunks": "chunk_id",
}


def _build_schema(collection_name: str) -> Any:
    """Build a CollectionSchema with dense HNSW + BM25 sparse fields."""
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)

    pk = _PK_FIELD[collection_name]
    schema.add_field(field_name=pk, datatype=DataType.VARCHAR, is_primary=True, max_length=64)
    # enable_analyzer=True activates the BM25 tokeniser on this field.
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=_MAX_VARCHAR, enable_analyzer=True)
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM)
    schema.add_field(field_name="sparse_embedding", datatype=DataType.SPARSE_FLOAT_VECTOR)

    for extra in _COLLECTION_EXTRA_FIELDS[collection_name]:
        schema.add_field(**extra)

    # BM25 function: tokenises ``text`` → auto-populates ``sparse_embedding``.
    bm25_fn = Function(
        name="bm25",
        input_field_names=["text"],
        output_field_names=["sparse_embedding"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_fn)
    return schema


def _build_index_params() -> Any:
    """Build HNSW (dense) + SPARSE_INVERTED_INDEX/BM25 (sparse) index params."""
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 256},
    )
    index_params.add_index(
        field_name="sparse_embedding",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )
    return index_params


class MilvusAdapter(VectorStoreProtocol):
    """Sync pymilvus wrapped in ``asyncio.to_thread`` to satisfy the async Protocol."""

    def __init__(self, uri: str) -> None:
        self._uri = uri
        self._client = MilvusClient(uri=uri)

    # ── Protocol methods ──────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Best-effort connectivity check. Never raises."""
        try:
            await asyncio.to_thread(self._client.list_collections)
            return True
        except Exception:
            return False

    async def create_collections_if_absent(self) -> None:
        """Create the three canonical collections when they do not already exist."""
        for name in _COLLECTION_EXTRA_FIELDS:
            await asyncio.to_thread(self._create_one_if_absent, name)

    async def upsert(self, collection: str, rows: list[dict[str, Any]]) -> None:
        """Insert or replace ``rows`` in ``collection``."""
        await asyncio.to_thread(self._client.upsert, collection_name=collection, data=rows)

    async def hybrid_search(
        self,
        collection: str,
        query_text: str,
        query_embedding: list[float],
        *,
        filters: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Dense HNSW + BM25 sparse hybrid search with RRF fusion (Epic 5)."""
        dense_req = AnnSearchRequest(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            expr=filters,
        )
        sparse_req = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse_embedding",
            param={"metric_type": "BM25"},
            limit=top_k,
            expr=filters,
        )
        results = await asyncio.to_thread(
            self._client.hybrid_search,
            collection_name=collection,
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(),
            limit=top_k,
        )
        return list(results[0]) if results else []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Best-effort close of the underlying MilvusClient."""
        try:
            await asyncio.to_thread(self._client.close)
        except Exception:
            pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _create_one_if_absent(self, name: str) -> None:
        if self._client.has_collection(name):
            logger.debug("Collection %r already exists — skipping creation", name)
            return
        schema = _build_schema(name)
        index_params = _build_index_params()
        self._client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )
        logger.info("Created collection %r with HNSW + BM25 index", name)
