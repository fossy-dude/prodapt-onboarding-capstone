---
baseline_commit: 3c5d585
---

# Story 5.3: RAG Pipeline — Milvus Hybrid Search

Status: done

## Story

As a **subscriber**,
I want the chatbot to answer general telecom FAQs and plan/billing questions by retrieving from a structured knowledge base,
so that I get accurate, grounded answers rather than hallucinated responses.

## Acceptance Criteria

1. **Given** a subscriber sends a query to the chatbot, **When** the Support Agent determines a RAG lookup is needed, **Then** the query is embedded using `text-embedding-3-small` (1536 dims) via Azure OpenAI. [Source: epics.md:1552; FR-26]
2. **And** a hybrid search is performed: HNSW vector search on `faq_chunks` / `plan_vectors` Milvus collections PLUS BM25 keyword search, results re-ranked by RRF (Reciprocal Rank Fusion). [Source: epics.md:1554; architecture.md:ARCH-8 §1.6.1 RAG Pipeline]
3. **And** the top-3 retrieved chunks are included in the LLM prompt as grounding context. [Source: epics.md:1556]
4. **And** the retrieval trace (**query text**, **top-k result chunk IDs**, **RRF scores**) is logged to LangFuse as a retrieval span. [the 1536-dim query embedding is intentionally not recorded — query text + scores suffice for observability and avoid ballooning LangFuse storage/egress; see Review Findings] [Source: epics.md:1558; FR-72]
5. **And** if no relevant chunk is found (all RRF scores below threshold 0.03 [threshold lowered from 0.1 — with k=60 the max reachable RRF is 2/61 ≈ 0.033, so 0.1 is unreachable; see Completion Notes and Review Findings]), the retriever returns an empty list; the agent responds: "I don't have information on that. Would you like to speak to a support agent?" [Source: epics.md:1560]
6. **And** the `rag_search` function signature is `async def rag_search(query: str, top_k: int = 3) -> list[RagChunk]` and is registered as a LangGraph tool callable for Story 5.4 to wire into the Support Agent graph. [Source: architecture.md §1.6.1]

## Tasks / Subtasks

- [x] **Task 1: RAG retriever module** (AC: #1–#5)
  - [x] Create `service_webapp/src/agents/rag/__init__.py` (empty).
  - [x] Create `service_webapp/src/agents/rag/retriever.py`.
  - [x] Define `RagChunk` dataclass: `collection: str, chunk_id: str, text: str, score: float, metadata: dict`.
  - [x] Class `HybridRetriever`:
    - Constructor: `__init__(self, milvus_uri: str, azure_client: AzureOpenAI, embedding_deployment: str, langfuse_client: Langfuse | None = None)`
    - `async def embed(self, text: str) -> list[float]`: calls `azure_client.embeddings.create(model=embedding_deployment, input=text)` — returns 1536-dim vector. Use `settings.embedding_model` ("text-embedding-3-small") and `settings.embedding_dimensions` (1536). [Source: service_webapp/src/core/config.py:67–68]
    - `async def search(self, query: str, top_k: int = 3) -> list[RagChunk]`: (1) embed query; (2) dense search on `faq_chunks` + `plan_vectors` via `pymilvus` client; (3) BM25 sparse search using `pymilvus.model.sparse.BM25EmbeddingFunction`; (4) RRF fusion; (5) return top_k chunks above threshold.
  - [x] RRF formula: `score_rrf(d) = sum(1 / (k + rank_i(d)))` for each ranked list, `k=60` (standard). Sort descending by RRF score. Filter out chunks with `rrf_score < 0.03` (no-match threshold). [Source: architecture.md §1.6.1 RAG Pipeline]
  - [x] Milvus client: `from pymilvus import MilvusClient`. Connect with `uri=settings.milvus_db_uri` (Milvus Lite embedded, no separate container). [Source: memory: arch_key_decisions — Milvus Lite]
  - [x] LangFuse span: if `langfuse_client` provided, wrap `search()` in a span: `langfuse_client.trace(...).span(name="rag_retrieval", input={"query": query}, output={"chunks": [c.chunk_id for c in results], "rrf_scores": [c.score for c in results]})`. [Source: epics.md:1558; FR-72]

- [x] **Task 2: Tool function for LangGraph** (AC: #6)
  - [x] In `service_webapp/src/agents/rag/retriever.py`, add module-level async function:
    ```python
    async def rag_search(query: str, top_k: int = 3) -> list[RagChunk]:
        ...
    ```
  - [x] This function uses a lazily-initialised singleton `_retriever: HybridRetriever` — set once at FastAPI startup via `set_retriever(retriever: HybridRetriever)`. This avoids passing dependencies into LangGraph tool closures. [Source: architecture.md §1.6.1]

- [x] **Task 3: Wire retriever at FastAPI startup** (AC: #1, #4)
  - [x] In `service_webapp/src/main.py` lifespan: after `azure_openai_client` is constructed, call `set_retriever(HybridRetriever(milvus_uri=settings.milvus_db_uri, azure_client=client, embedding_deployment=settings.embedding_model))`. [Source: service_webapp/src/main.py lifespan pattern]

- [x] **Task 4: Milvus collection compatibility** (AC: #2)
  - [x] Collections `faq_chunks` and `plan_vectors` were seeded in Story 2.7. Verify field names by reading `service_webapp/src/adapters/milvus.py` or the seeding script before writing query code. [Source: 2-7-milvus-lite-initialisation-vector-seeding.md]
  - [x] Dense search: `client.search(collection_name="faq_chunks", data=[query_vector], anns_field="embedding", limit=top_k * 3, output_fields=["chunk_id", "text", "metadata"])`. Repeat for `plan_vectors`.
  - [x] BM25: use `pymilvus.model.sparse.BM25EmbeddingFunction` fitted on the collection corpus (either loaded from a persisted state or refitted at startup). Sparse search via `client.search(..., anns_field="sparse_embedding", ...)`.

- [x] **Task 5: Tests** (AC: #1–#6)
  - [x] `service_webapp/tests/unit/test_rag_retriever.py`: mock `AzureOpenAI` client and `MilvusClient`. Test: query returns 3 chunks sorted by RRF desc; all chunks below threshold → empty list; LangFuse span called with correct input/output shape.
  - [x] `service_webapp/tests/unit/test_rag_search_tool.py`: call `rag_search("what is my balance?")` via module-level function with singleton retriever set to mock. Verify returns `list[RagChunk]`.
  - [x] Integration test (`@pytest.mark.slow`): requires live Milvus Lite DB path with seeded data. Skip if `settings.milvus_db_uri` path doesn't exist.

- [x] **Task 6: Tox deps** (AC: #1)
  - [x] Add `openai>=1.0` to `service_webapp/pyproject.toml` `[tool.tox.env.lint] deps` AND `[tool.tox.env.test] deps`. `pymilvus[milvus-lite]` should already be present from Story 2.7 — verify.
  - [x] Add `openai>=1.0` to `[project.dependencies]` in `service_webapp/pyproject.toml` (runtime dep for agent stories).

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

- Initial unit-test run failed (7/14): mocked `MilvusClient.search` returned the
  inner hit list directly, but real pymilvus wraps it one level deeper
  (`[[hit, hit]]` — one result-list per query vector). The retriever code
  (`list(results[0])`) was correct for real pymilvus; fixed the tests by adding a
  `_results(*hits)` helper that wraps each side-effect entry. All 14 then passed.
- Ruff RUF002 flagged two EN dashes (`#1–#5`) in test docstrings; replaced with
  hyphens. Em dashes (`—`) are left as-is (existing codebase convention).

### Completion Notes List

- **Implemented:** `HybridRetriever` (dense HNSW + BM25 sparse per collection,
  manual RRF fusion) and the module-level `rag_search` LangGraph tool callable
  with a `set_retriever()` singleton, wired into the FastAPI lifespan.
- **Deviations from story text (arch-wins / SDK-version — flagged to user):**
  1. **BM25 sparse search:** the Story 2.7 collections use Milvus's *native BM25
     analyzer* on the `text` field (auto-populates `sparse_embedding`), so sparse
     search takes the raw query text (`data=[query]`,
     `anns_field="sparse_embedding"`) — NOT a separately-fitted
     `pymilvus.model.sparse.BM25EmbeddingFunction`, which is incompatible with
     this analyzer-backed schema. Consistent with the existing
     `MilvusAdapter.hybrid_search`.
  2. **RRF no-match threshold = 0.03 (not 0.1):** with `k=60`, a chunk can
     contribute at most `2 × 1/61 ≈ 0.033` (it appears in exactly two ranked
     lists — dense + sparse — for its own collection), so the story's `0.1` is
     mathematically unreachable and would make `rag_search` return empty for
     every query. **User decision (2026-06-24):** keep `k=60` (standard) and
     lower the threshold to `0.03`. A chunk must agree across BOTH modalities
     near the top of their lists to survive. Exposed as module constants
     `_RRF_K=60` and `_RRF_NO_MATCH_THRESHOLD=0.03`.
  3. **LangFuse v4 API:** `langfuse>=2` resolves to v4.x, which removed the v2
     `client.trace().span()` surface. The retrieval span is opened with
     `start_as_current_observation(name="rag_retrieval", as_type="span")`,
     consistent with the existing `trace_agent` decorator. Input records only the
     query text (no PII/MSISDN); output records chunk IDs + RRF scores.
- **`output_fields`:** collections have no `metadata` column (the seeded schema
  uses explicit scalar fields per collection); `RagChunk.metadata` is built from
  the per-collection extra scalars (`category`/`source_doc`/`plan_type` for
  `faq_chunks`; `plan_type`/`price`/`validity` for `plan_vectors`).
- **Startup wiring:** Azure OpenAI + LangFuse are optional — empty key/config
  degrades gracefully to "no grounding" (logged warning), never crashes boot.
  The auto-formatter hoisted the optional `openai`/`apscheduler` imports to
  module level with try/except guards; behaviour unchanged.
- **Testing:** 14 new unit tests (RRF ordering, top_k, threshold-empty, metadata,
  anns_field/collection args, LangFuse span shape, no-client path, span-open
  failure fallback, empty-results tolerance, tool delegation/top_k/uninitialised).
  Integration test marked `@pytest.mark.slow @pytest.mark.integration`, skips
  unless a seeded Milvus DB + Azure config are present. All 14 pass; full unit
  suite 279 pass. The 11 `test_synthetic_helpers.py` failures are pre-existing
  and environmental (`faker` is a tox-only dev dep absent from the local venv) —
  unrelated to this story. Ruff lint + format and pyrefly (0 errors) clean.

### File List

- `service_webapp/src/agents/rag/__init__.py` (NEW)
- `service_webapp/src/agents/rag/retriever.py` (NEW)
- `service_webapp/src/main.py` (MODIFIED — lifespan wiring + shutdown close)
- `service_webapp/pyproject.toml` (MODIFIED — `openai>=1.0` added to
  `[project.dependencies]`, `[tool.tox.env.lint].deps`, `[tool.tox.env.test].deps`)
- `service_webapp/tests/unit/test_rag_retriever.py` (NEW)
- `service_webapp/tests/unit/test_rag_search_tool.py` (NEW)
- `service_webapp/tests/integration/test_rag_integration.py` (NEW, slow)

### Review Findings

Code review (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance
Auditor) on 2026-06-24.

Decision-needed:

- [x] [Review][Decision] **RRF no-match threshold — spec/code reconciliation + aggressiveness.** Spec AC #5 still reads `0.1`; code ships `0.03` (verified: with k=60, max reachable RRF for a doc in both lists = 2/61 ≈ 0.0328, so 0.1 is mathematically unreachable — every query would return empty). User already chose 0.03 on 2026-06-24, but the AC text was never amended. Separately, Edge Hunter notes 0.03 is aggressive: a chunk at rank-1 dense-only (no sparse hit) scores 1/61 ≈ 0.0164 and is dropped, so short FAQ queries may return `[]` more often than the support agent expects. Options: (a) keep 0.03 + amend spec AC text; (b) lower threshold to ~0.015 or add an "always keep top-1 dense" fallback; (c) lower k (e.g. k=10 → 0.1 becomes reachable) and restore the literal 0.1. [retriever.py:68, spec AC #5]
- [x] [Review][Decision] **AC #4 "query embedding" not captured in LangFuse span.** Span input records `{"query": <text>}` only; the 1536-dim embedding is computed (`_search`) but never recorded. AC #4 literally lists "query embedding, top-k results, RRF scores". Options: (a) amend AC #4 to "query text" with a PII/storage rationale note; (b) actually log the embedding (verbose). [retriever.py:160-179]
- [x] [Review][Decision] **`rag_search` raises `RuntimeError` when Azure unconfigured.** Boot degrades gracefully (`app.state.rag_retriever = None`) but at call time `rag_search` raises because `set_retriever` was never called — every Azure-less deployment's first RAG tool call hard-fails unless Story 5.4 catches it. Options: (a) return `[]` (matches the "no grounding found" empty contract); (b) keep raise and ensure 5.4 catches. [retriever.py:328-329]
- [x] [Review][Decision] **Cross-collection top-k has no diversity floor.** Final slice is across both collections jointly; if `faq_chunks` matches 5 chunks strongly and `plan_vectors` matches 0, the agent gets all-FAQ grounding even for a plan question. Options: (a) accept (simplest); (b) add a per-collection quota/diversity floor. [retriever.py:225-226]

Patch (unambiguous fixes):

- [x] [Review][Patch] **`top_k<=0` crashes Milvus with `ParamError`** (`limit value 0 is illegal`) — the LangGraph tool exposes `top_k` to the LLM, which may pass 0. Clamp to `max(top_k, 1)`. [retriever.py:192]
- [x] [Review][Patch] **PK read via `hit.get("id")` is dead code** — real pymilvus returns the PK under its field name (`chunk_id`/`plan_id`), never `"id"`; code only works via the `entity.get(pk_field)` fallback. Unit-test mock injects a fake `"id"` key so tests exercise the wrong branch. Fix mock to key by the real PK name; read `hit.get(pk_field)` directly. [retriever.py:247 + test_rag_retriever.py]
- [x] [Review][Patch] **Empty-results guard is dead code + mock shape wrong** — real pymilvus always returns a truthy `SearchResult` (even empty → `[[]]`), so `if results else []` never fires; the empty-tolerance test mocks `[]` (falsy), exercising the dead branch. Fix mock to `[[]]` and simplify the guard. [retriever.py:277,299 + test_rag_retriever.py]
- [x] [Review][Patch] **`embed()` unguarded `response.data[0]`** — `IndexError` if Azure returns empty `data` (filtered/rate-limit). Add a guard. [retriever.py:141]
- [x] [Review][Patch] **No `metric_type`/`search_params` passed** — diverges from `MilvusAdapter.hybrid_search` which explicitly sets `COSINE`/`BM25`; relies on implicit index inference. Mirror the adapter. [retriever.py:269,291]
- [x] [Review][Patch] **Singleton never cleared on shutdown** — `app.state.rag_retriever.close()` runs but `set_retriever(None)` is missing, so the module global points at a CLOSED client; a later `rag_search` calls a closed MilvusClient instead of raising "not initialised". Add `set_retriever(None)` in shutdown. [main.py shutdown]
- [x] [Review][Patch] **Resource leak on partial-init failure** — if `AzureOpenAI(...)` + `HybridRetriever(...)` succeed (Milvus handle open) but a later init line raises, the `except` nulls state without `.close()`-ing the opened retriever. Construct retriever last and close it in the except. [main.py init]
- [x] [Review][Patch] **`_search_traced` manual `__exit__(*sys.exc_info())` + swallowed failures hide LangFuse errors** — defeats observability; use a proper `with observation_cm as observation:` block (`trace_agent` pattern). [retriever.py:160-187]
- [x] [Review][Patch] **`_record_hit` builds metadata only on first sighting** — if the first hit's entity lacks a metadata field a later hit carries, it is lost. Merge metadata across sightings. [retriever.py:252]
- [x] [Review][Patch] **Threshold value not pinned by a test assertion** — the empty-threshold test only asserts `results == []`; changing 0.03 would not fail it. Add an assertion on the actual RRF score / boundary. [test_rag_retriever.py]

Defer (pre-existing / out-of-scope / other-story):

- [x] [Review][Defer] **`_dispatch_notification_events` Kafka offset commit outside `db.transaction()`** — non-atomic; duplicate inserts / lost notifications on broker hiccup. Story 4.x, NOT 5.3. [main.py] — deferred, pre-existing
- [x] [Review][Defer] **`data_nudge_consumer` gated on `notification_dispatcher`** — conflates two unrelated consumers; DATA_NUDGE never starts if the dispatcher is absent. Story 4.x, NOT 5.3. [main.py] — deferred, pre-existing
- [x] [Review][Defer] **Commit scope hygiene** — `main.py`/`pyproject.toml` diff bundles unrelated Stories 4.1/4.2/4.3/5.2 changes into the 5.3 commit. Not an AC issue; consider splitting before merge. — deferred, pre-existing
- [x] [Review][Defer] **`RagChunk` plain dataclass, not JSON-serializable** — Story 5.4's LangGraph tool result will need `dataclasses.asdict()` or the LLM can't consume the output. Flag for 5.4. [retriever.py:90-104] — deferred, downstream (5.4)
- [x] [Review][Defer] **`rag_search` not yet wrapped as a LangGraph `@tool`/`ToolNode`** — correctly deferred to 5.4 per AC #6; confirm 5.4 owns registration. [retriever.py:322] — deferred, downstream (5.4)
- [x] [Review][Defer] **Two `MilvusClient` instances on the same Milvus Lite file** (adapter + retriever) — works today; retriever could reuse `app.state.milvus_adapter`. Design note. [main.py] — deferred, design
- [x] [Review][Defer] **Singleton has no lock** — `set_retriever` called once at startup; concurrent reads verified safe. Theoretical only. [retriever.py:313] — deferred, theoretical
- [x] [Review][Defer] **Falsy PK `or ""` chain** — real Milvus PKs are UUID/strings, never falsy. Low-value defensive. [retriever.py:247] — deferred, low-value

Dismissed as noise: 2 (speculative future `asyncio.gather` thread-safety; duplicate threshold-assertion note folded into a patch).

## Change Log

- 2026-06-24 (review): 3-layer adversarial code review (Blind Hunter, Edge Case
  Hunter, Acceptance Auditor). 4 decisions resolved: (D1) keep threshold 0.03 +
  amend AC #5/Task 1 text; (D2) amend AC #4 to "query text + chunk IDs + RRF
  scores" (embedding intentionally omitted); (D3) `rag_search` returns `[]` +
  warning when uninitialised (graceful degradation, matches empty-grounding
  contract) — agent fallback handling deferred to 5.4; (D4) accept no
  per-collection diversity floor (defer). 11 code/test patches applied: top_k
  clamp (min 1), PK read under real field name + faithful mock, empty-results
  guard + `[[]]` mock, embed empty-data guard, explicit `metric_type` (COSINE/
  BM25) `search_params`, `set_retriever(None)` on shutdown + on init failure,
  init resource-leak close, `_search_traced` proper `with` context-manager,
  metadata merge across sightings, threshold pinned by assertion. 8 items
  deferred (pre-existing Story 4.x consumer/offset issues, commit scope hygiene,
  RagChunk JSON-serialisation + @tool registration for 5.4, two-MilvusClient
  reuse, singleton locking, falsy-PK guard). Spec AC #4/#5 text reconciled.
  Status: review -> done.

- 2026-06-24: Story 5.3 developed — hybrid RAG retriever (dense + BM25 + RRF
  k=60, threshold 0.03) + `rag_search` LangGraph tool + FastAPI lifespan wiring
  + unit/integration tests. Threshold lowered from spec's unreachable 0.1 to 0.03
  per user decision; BM25 uses native analyzer (arch-wins over BM25EmbeddingFunction);
  LangFuse v4 span API. Status: ready-for-dev -> review.
