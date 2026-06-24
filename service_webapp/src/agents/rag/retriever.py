"""Hybrid RAG retriever over Milvus Lite (Story 5.3; architecture §1.6.1).

Implements the Support Agent's grounding path:

1. Embed the subscriber query with ``text-embedding-3-small`` (1536 dims) via the
   Azure OpenAI ``AzureOpenAI`` client.
2. Run a **dense** HNSW search AND a **BM25** sparse search on each of the
   ``faq_chunks`` and ``plan_vectors`` collections (seeded in Story 2.7).
3. Fuse the per-collection ranked lists with **Reciprocal Rank Fusion** (RRF,
   ``k=60``) — the standard rank-based combiner robust to score-scale
   differences between dense and lexical retrieval.
4. Drop fused chunks below the no-match threshold and return the top-k as
   :class:`RagChunk`, ready to inject as grounding context into the LLM prompt.

A retrieval span is recorded to LangFuse (FR-72) when a client is supplied;
input records only the query text (never the raw MSISDN — architecture §1.11.6).

Deviation notes (arch-wins over the story text, see Completion Notes):

* The seeded collections (Story 2.7 / ``adapters/milvus.py``) use Milvus's
  **native BM25 analyzer** on the ``text`` field, which auto-populates the
  ``sparse_embedding`` column. Sparse search therefore takes the raw query text
  (``data=[query]``, ``anns_field="sparse_embedding"``) — a separately-fitted
  ``pymilvus.model.sparse.BM25EmbeddingFunction`` is neither needed nor
  compatible with this analyzer-backed schema.
* The no-match threshold is ``0.03`` (not the ``0.1`` in the story prose). With
  ``k=60`` a chunk can contribute at most ``2 x 1/61 ≈ 0.033`` (it appears in
  exactly two ranked lists — dense + sparse — for its own collection), so ``0.1``
  is mathematically unreachable and would make the retriever return empty for
  every query. ``0.03`` keeps the no-match guard functional: a chunk must agree
  across BOTH modalities near the top of their lists to survive. User decision
  (2026-06-24).
* LangFuse v4 (``langfuse>=2`` resolves to v4.x) removed the v2
  ``client.trace().span()`` surface; the span is opened with the v4
  ``start_as_current_observation(as_type="span")`` API, consistent with the
  existing ``trace_agent`` decorator.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pymilvus import MilvusClient

if TYPE_CHECKING:
    from langfuse import Langfuse
    from openai import AzureOpenAI

logger = logging.getLogger(__name__)

__all__ = [
    "HybridRetriever",
    "RagChunk",
    "rag_search",
    "set_retriever",
]

# ── RRF constants (architecture §1.6.1) ────────────────────────────────────────
# k=60 is the standard value from the original RRF paper — dampens high-ranked
# results so fusion is robust to the score-scale gap between dense (cosine) and
# lexical (BM25) retrieval. Hardcoded per the dev note (no config needed).
_RRF_K: int = 60
# No-match cutoff. See module docstring for why this is 0.03 rather than 0.1.
_RRF_NO_MATCH_THRESHOLD: float = 0.03
# How many candidates to pull from each (collection, modality) search before
# fusion. Wider than top_k so RRF has a ranked tail to fuse over.
_CANDIDATE_MULTIPLIER: int = 3

# Collections searched (seeded in Story 2.7 / adapters/milvus.py). Both carry a
# ``text`` (BM25-analyzer) field, a dense ``embedding`` (1536) and a
# ``sparse_embedding`` (native BM25 output) field.
_COLLECTIONS: tuple[str, ...] = ("faq_chunks", "plan_vectors")

# Primary-key field and extra scalar fields per collection (from adapters/milvus.py
# _PK_FIELD / _COLLECTION_EXTRA_FIELDS). The extra scalars become RagChunk.metadata.
_PK_FIELD: dict[str, str] = {
    "faq_chunks": "chunk_id",
    "plan_vectors": "plan_id",
}
_METADATA_FIELDS: dict[str, list[str]] = {
    "faq_chunks": ["category", "source_doc", "plan_type"],
    "plan_vectors": ["plan_type", "price", "validity"],
}


@dataclass
class RagChunk:
    """One retrieved grounding chunk.

    A plain ``@dataclass`` (not a pydantic model) so the ``dict`` metadata field
    needs no ``TYPE_CHECKING`` annotation workaround (memory:
    uuid7-import-and-pydantic-typecheck-gotchas). ``score`` is the fused RRF
    score; ``collection`` identifies which Milvus collection the chunk came from.
    """

    collection: str
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class HybridRetriever:
    """Dense + BM25 hybrid retriever with manual RRF fusion.

    Owns its own :class:`pymilvus.MilvusClient` (Milvus Lite, embedded — no
    separate server). The Azure client and (optional) LangFuse client are
    injected so tests pass fakes instead of hitting the network.
    """

    def __init__(
        self,
        milvus_uri: str,
        azure_client: AzureOpenAI,
        embedding_deployment: str,
        langfuse_client: Langfuse | None = None,
    ) -> None:
        self._milvus = MilvusClient(uri=milvus_uri)
        self._azure = azure_client
        # The ``model`` passed to ``embeddings.create`` — for Azure this is the
        # deployment name; the codebase convention (config.py:75) names the
        # embedding deployment after the model: "text-embedding-3-small".
        self._embedding_deployment = embedding_deployment
        self._langfuse = langfuse_client

    async def embed(self, text: str) -> list[float]:
        """Embed ``text`` to a 1536-dim vector via Azure OpenAI.

        The openai SDK call is synchronous; ``to_thread`` keeps the event loop
        free. Returns ``data[0].embedding`` (single input → single vector).
        """
        response = await asyncio.to_thread(
            self._azure.embeddings.create,
            model=self._embedding_deployment,
            input=text,
        )
        return list(response.data[0].embedding)

    async def search(self, query: str, top_k: int = 3) -> list[RagChunk]:
        """Hybrid search: embed → dense + BM25 per collection → RRF → top_k.

        Records a ``rag_retrieval`` span to LangFuse when a client is configured.
        Chunks whose fused RRF score falls below ``_RRF_NO_MATCH_THRESHOLD`` are
        dropped (AC #5): an empty result signals "no grounding found".
        """
        if self._langfuse is not None:
            return await self._search_traced(query, top_k)
        return await self._search(query, top_k)

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _search_traced(self, query: str, top_k: int) -> list[RagChunk]:
        """Wrap :meth:`_search` in a LangFuse ``rag_retrieval`` span (FR-72)."""
        assert self._langfuse is not None
        try:
            observation_cm = self._langfuse.start_as_current_observation(
                name="rag_retrieval",
                as_type="span",
                # PII hygiene (§1.11.6): only the query text, never the MSISDN.
                input={"query": query},
            )
            observation = observation_cm.__enter__()
        except Exception as exc:  # observability must never break the business call
            logger.warning("LangFuse rag_retrieval span open failed: %s", exc)
            return await self._search(query, top_k)

        try:
            results = await self._search(query, top_k)
            try:
                observation.update(
                    output={
                        "chunks": [c.chunk_id for c in results],
                        "rrf_scores": [c.score for c in results],
                    },
                )
            except Exception as exc:
                logger.warning("LangFuse rag_retrieval span update failed: %s", exc)
            return results
        finally:
            try:
                observation_cm.__exit__(*sys.exc_info())
            except Exception:
                pass

    async def _search(self, query: str, top_k: int) -> list[RagChunk]:
        """Fuse dense + BM25 results across both collections via RRF."""
        query_vector = await self.embed(query)
        candidate_limit = max(top_k * _CANDIDATE_MULTIPLIER, top_k)

        # Map of doc-key -> {chunk, rank-in-each-list}. doc-key is the stable
        # identity across the dense/sparse lists of one collection.
        docs: dict[tuple[str, str], dict[str, Any]] = {}
        # Per-list ranked ordering, used to compute RRF ranks (1-based).
        lists: list[list[tuple[str, str]]] = []

        for collection in _COLLECTIONS:
            pk_field = _PK_FIELD[collection]
            output_fields = ["text", *_METADATA_FIELDS[collection]]

            dense_hits = await self._dense_search(collection, query_vector, candidate_limit, output_fields)
            sparse_hits = await self._sparse_search(collection, query, candidate_limit, output_fields)

            # Build the two ranked lists (dense + sparse) for this collection.
            # _record_hit is idempotent — registering the same hit twice just
            # returns its existing doc-key — so dense/sparse share one docs map.
            dense_keys = [self._record_hit(collection, pk_field, hit, docs) for hit in dense_hits]
            sparse_keys = [self._record_hit(collection, pk_field, hit, docs) for hit in sparse_hits]
            lists.append([k for k in dense_keys if k is not None])
            lists.append([k for k in sparse_keys if k is not None])

        # RRF: score(d) = Σ 1 / (k + rank_i(d)) over every ranked list, rank 1-based.
        for key, doc in docs.items():
            rrf = 0.0
            for ranked in lists:
                for idx, k2 in enumerate(ranked, start=1):
                    if k2 == key:
                        rrf += 1.0 / (_RRF_K + idx)
                        break
            doc["rrf_score"] = rrf

        fused = sorted(docs.values(), key=lambda d: d["rrf_score"], reverse=True)
        kept = [d for d in fused if d["rrf_score"] >= _RRF_NO_MATCH_THRESHOLD][:top_k]
        return [
            RagChunk(
                collection=d["collection"],
                chunk_id=d["chunk_id"],
                text=d["text"],
                score=d["rrf_score"],
                metadata=d["metadata"],
            )
            for d in kept
        ]

    def _record_hit(
        self,
        collection: str,
        pk_field: str,
        hit: dict[str, Any],
        docs: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[str, str] | None:
        """Idempotently register a search hit; return its doc-key (or None)."""
        entity = hit.get("entity") or {}
        chunk_id = hit.get("id") or entity.get(pk_field) or ""
        if not chunk_id:
            return None
        key = (collection, str(chunk_id))
        if key not in docs:
            metadata = {fname: entity[fname] for fname in _METADATA_FIELDS[collection] if fname in entity}
            docs[key] = {
                "collection": collection,
                "chunk_id": str(chunk_id),
                "text": entity.get("text", ""),
                "metadata": metadata,
            }
        return key

    async def _dense_search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        """HNSW vector search on the dense ``embedding`` field."""
        results = await asyncio.to_thread(
            self._milvus.search,
            collection_name=collection,
            data=[query_vector],
            anns_field="embedding",
            limit=limit,
            output_fields=output_fields,
        )
        return list(results[0]) if results else []

    async def _sparse_search(
        self,
        collection: str,
        query_text: str,
        limit: int,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        """BM25 sparse search on the analyzer-backed ``sparse_embedding`` field.

        The native BM25 function tokenises the query text server-side, so the
        raw query string is passed as ``data`` (not a pre-fitted sparse vector).
        """
        results = await asyncio.to_thread(
            self._milvus.search,
            collection_name=collection,
            data=[query_text],
            anns_field="sparse_embedding",
            limit=limit,
            output_fields=output_fields,
        )
        return list(results[0]) if results else []

    async def close(self) -> None:
        """Best-effort close of the underlying MilvusClient."""
        try:
            await asyncio.to_thread(self._milvus.close)
        except Exception:
            pass


# ── LangGraph tool surface (AC #6) ────────────────────────────────────────────
# A lazily-initialised singleton set once at FastAPI startup, so the module-level
# ``rag_search`` tool callable has no dependency-injection closure to thread
# through the LangGraph tool registry (architecture §1.6.1).
_retriever: HybridRetriever | None = None


def set_retriever(retriever: HybridRetriever | None) -> None:
    """Set (or clear with ``None``) the process-wide retriever singleton."""
    global _retriever
    _retriever = retriever


async def rag_search(query: str, top_k: int = 3) -> list[RagChunk]:
    """LangGraph tool callable: hybrid RAG search returning top-k grounded chunks.

    Raises ``RuntimeError`` if :func:`set_retriever` was not called at startup
    (the Support Agent in Story 5.4 must not be reachable before wiring).
    """
    if _retriever is None:
        raise RuntimeError("HybridRetriever not initialised — call set_retriever() at FastAPI startup")
    return await _retriever.search(query, top_k=top_k)
