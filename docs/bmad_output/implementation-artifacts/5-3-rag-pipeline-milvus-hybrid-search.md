---
baseline_commit: 3c5d585
---

# Story 5.3: RAG Pipeline — Milvus Hybrid Search

Status: in-progress

## Story

As a **subscriber**,
I want the chatbot to answer general telecom FAQs and plan/billing questions by retrieving from a structured knowledge base,
so that I get accurate, grounded answers rather than hallucinated responses.

## Acceptance Criteria

1. **Given** a subscriber sends a query to the chatbot, **When** the Support Agent determines a RAG lookup is needed, **Then** the query is embedded using `text-embedding-3-small` (1536 dims) via Azure OpenAI. [Source: epics.md:1552; FR-26]
2. **And** a hybrid search is performed: HNSW vector search on `faq_chunks` / `plan_vectors` Milvus collections PLUS BM25 keyword search, results re-ranked by RRF (Reciprocal Rank Fusion). [Source: epics.md:1554; architecture.md:ARCH-8 §1.6.1 RAG Pipeline]
3. **And** the top-3 retrieved chunks are included in the LLM prompt as grounding context. [Source: epics.md:1556]
4. **And** the retrieval trace (query embedding, top-k results, RRF scores) is logged to LangFuse as a retrieval span. [Source: epics.md:1558; FR-72]
5. **And** if no relevant chunk is found (all RRF scores below threshold 0.1), the retriever returns an empty list; the agent responds: "I don't have information on that. Would you like to speak to a support agent?" [Source: epics.md:1560]
6. **And** the `rag_search` function signature is `async def rag_search(query: str, top_k: int = 3) -> list[RagChunk]` and is registered as a LangGraph tool callable for Story 5.4 to wire into the Support Agent graph. [Source: architecture.md §1.6.1]

## Tasks / Subtasks

- [ ] **Task 1: RAG retriever module** (AC: #1–#5)
  - [ ] Create `service_webapp/src/agents/rag/__init__.py` (empty).
  - [ ] Create `service_webapp/src/agents/rag/retriever.py`.
  - [ ] Define `RagChunk` dataclass: `collection: str, chunk_id: str, text: str, score: float, metadata: dict`.
  - [ ] Class `HybridRetriever`:
    - Constructor: `__init__(self, milvus_uri: str, azure_client: AzureOpenAI, embedding_deployment: str, langfuse_client: Langfuse | None = None)`
    - `async def embed(self, text: str) -> list[float]`: calls `azure_client.embeddings.create(model=embedding_deployment, input=text)` — returns 1536-dim vector. Use `settings.embedding_model` ("text-embedding-3-small") and `settings.embedding_dimensions` (1536). [Source: service_webapp/src/core/config.py:67–68]
    - `async def search(self, query: str, top_k: int = 3) -> list[RagChunk]`: (1) embed query; (2) dense search on `faq_chunks` + `plan_vectors` via `pymilvus` client; (3) BM25 sparse search using `pymilvus.model.sparse.BM25EmbeddingFunction`; (4) RRF fusion; (5) return top_k chunks above threshold.
  - [ ] RRF formula: `score_rrf(d) = sum(1 / (k + rank_i(d)))` for each ranked list, `k=60` (standard). Sort descending by RRF score. Filter out chunks with `rrf_score < 0.1` (no-match threshold). [Source: architecture.md §1.6.1 RAG Pipeline]
  - [ ] Milvus client: `from pymilvus import MilvusClient`. Connect with `uri=settings.milvus_db_uri` (Milvus Lite embedded, no separate container). [Source: memory: arch_key_decisions — Milvus Lite]
  - [ ] LangFuse span: if `langfuse_client` provided, wrap `search()` in a span: `langfuse_client.trace(...).span(name="rag_retrieval", input={"query": query}, output={"chunks": [c.chunk_id for c in results], "rrf_scores": [c.score for c in results]})`. [Source: epics.md:1558; FR-72]

- [ ] **Task 2: Tool function for LangGraph** (AC: #6)
  - [ ] In `service_webapp/src/agents/rag/retriever.py`, add module-level async function:
    ```python
    async def rag_search(query: str, top_k: int = 3) -> list[RagChunk]:
        ...
    ```
  - [ ] This function uses a lazily-initialised singleton `_retriever: HybridRetriever` — set once at FastAPI startup via `set_retriever(retriever: HybridRetriever)`. This avoids passing dependencies into LangGraph tool closures. [Source: architecture.md §1.6.1]

- [ ] **Task 3: Wire retriever at FastAPI startup** (AC: #1, #4)
  - [ ] In `service_webapp/src/main.py` lifespan: after `azure_openai_client` is constructed, call `set_retriever(HybridRetriever(milvus_uri=settings.milvus_db_uri, azure_client=client, embedding_deployment=settings.embedding_model))`. [Source: service_webapp/src/main.py lifespan pattern]

- [ ] **Task 4: Milvus collection compatibility** (AC: #2)
  - [ ] Collections `faq_chunks` and `plan_vectors` were seeded in Story 2.7. Verify field names by reading `service_webapp/src/adapters/milvus.py` or the seeding script before writing query code. [Source: 2-7-milvus-lite-initialisation-vector-seeding.md]
  - [ ] Dense search: `client.search(collection_name="faq_chunks", data=[query_vector], anns_field="embedding", limit=top_k * 3, output_fields=["chunk_id", "text", "metadata"])`. Repeat for `plan_vectors`.
  - [ ] BM25: use `pymilvus.model.sparse.BM25EmbeddingFunction` fitted on the collection corpus (either loaded from a persisted state or refitted at startup). Sparse search via `client.search(..., anns_field="sparse_embedding", ...)`.

- [ ] **Task 5: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_rag_retriever.py`: mock `AzureOpenAI` client and `MilvusClient`. Test: query returns 3 chunks sorted by RRF desc; all chunks below threshold → empty list; LangFuse span called with correct input/output shape.
  - [ ] `service_webapp/tests/unit/test_rag_search_tool.py`: call `rag_search("what is my balance?")` via module-level function with singleton retriever set to mock. Verify returns `list[RagChunk]`.
  - [ ] Integration test (`@pytest.mark.slow`): requires live Milvus Lite DB path with seeded data. Skip if `settings.milvus_db_uri` path doesn't exist.

- [ ] **Task 6: Tox deps** (AC: #1)
  - [ ] Add `openai>=1.0` to `service_webapp/pyproject.toml` `[tool.tox.env.lint] deps` AND `[tool.tox.env.test] deps`. `pymilvus[milvus-lite]` should already be present from Story 2.7 — verify.
  - [ ] Add `openai>=1.0` to `[project.dependencies]` in `service_webapp/pyproject.toml` (runtime dep for agent stories).

## Dev Notes

### Milvus Lite — no container

`pymilvus[milvus-lite]` runs embedded in-process. Connect via `MilvusClient(uri=settings.milvus_db_uri)`. The URI defaults to `/app/data/milvus/sboai.db` (Docker volume) and `./data/milvus/sboai.db` locally. Do NOT attempt to start a separate Milvus server. [Source: memory: arch_key_decisions — Milvus Lite]

### Azure OpenAI embeddings — existing config

`settings.embedding_model = "text-embedding-3-small"` and `settings.embedding_dimensions = 1536` are already in `service_webapp/src/core/config.py:67–68`. The Azure client (`AzureOpenAI`) needs `api_key=settings.azure_openai_api_key`, `azure_endpoint=settings.azure_openai_endpoint`, `api_version=settings.azure_openai_api_version`. [Source: service_webapp/src/core/config.py:61–68]

### openai SDK — NOT azure-specific import

Use `from openai import AzureOpenAI` — this is the same `openai` package (>= 1.0) that supports Azure. Do NOT install `azure-openai` separately. [Source: openai SDK docs]

### RRF k=60 is standard

The constant `k=60` in the RRF formula is the standard recommendation from the original paper. It dampens the impact of high-ranked results, making fusion robust. Keep it hardcoded — no config needed. [Source: architecture.md §1.6.1 RAG Pipeline]

### BM25 state

`BM25EmbeddingFunction` needs to be fitted on the corpus. In MVP, fit at startup by fetching all chunk texts from Milvus (limited to a few thousand chunks — acceptable for Milvus Lite). Cache the fitted function in the `HybridRetriever` instance. This avoids re-fitting per query.

### pydantic gotcha — from memory

If `RagChunk` is a pydantic `BaseModel` (not a plain dataclass), `dict` field annotation must NOT be behind `TYPE_CHECKING`. Use plain dataclass (`@dataclass`) to avoid pydantic annotation resolution issues. [Source: memory: uuid7-import-and-pydantic-typecheck-gotchas]

### LangFuse span naming

Follow LangFuse semantic: `name="rag_retrieval"`, input includes `query` (NEVER the raw MSISDN — only query text), output includes chunk IDs and scores. No PII in spans. [Source: architecture.md:ARCH-32]

### Project Structure Notes

- New dir: `service_webapp/src/agents/rag/` (NEW — agents/ dir doesn't exist yet)
- Modified: `service_webapp/src/main.py` (lifespan wiring)
- Modified: `service_webapp/pyproject.toml` (add `openai>=1.0` to deps + tox envs)
- No migration, no frontend changes, no DB changes.

### References

- [Source: epics.md §1.8.3 — Story 5.3 acceptance criteria]
- [Source: architecture.md §1.6.1 — RAG Pipeline (dense, BM25, RRF)]
- [Source: architecture.md:ARCH-8 — Milvus hybrid search]
- [Source: architecture.md:FR-26 — RAG FAQ assistant]
- [Source: architecture.md:FR-72 — LangFuse agentic observability]
- [Source: service_webapp/src/core/config.py:61–68 — Azure OpenAI + embedding config]
- [Source: 2-7-milvus-lite-initialisation-vector-seeding.md — faq_chunks / plan_vectors collections]
- [Source: memory: arch_key_decisions — Milvus Lite, embedding_model]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
