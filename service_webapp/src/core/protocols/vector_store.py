"""Vector store port (architecture §1.12.1 — VectorStoreProtocol seam)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Minimal vector store port mirroring DatabaseProtocol/CacheProtocol style."""

    async def ping(self) -> bool:
        """Return ``True`` if the vector store is reachable, ``False`` otherwise.

        Must never raise.
        """
        ...

    async def create_collections_if_absent(self) -> None:
        """Create the three canonical collections (faq_chunks, plan_vectors, sop_chunks) if they do not exist."""
        ...

    async def upsert(self, collection: str, rows: list[dict[str, Any]]) -> None:
        """Insert or replace rows in ``collection``."""
        ...

    async def hybrid_search(
        self,
        collection: str,
        query_text: str,
        query_embedding: list[float],
        *,
        filters: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Dense HNSW + BM25 sparse hybrid search with RRF fusion (Epic 5 consumer)."""
        ...
