# Story 2.7: Milvus Lite Initialisation & Vector Seeding

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want Milvus Lite running embedded in service_webapp and all three vector collections seeded from the synthetic knowledge base,
so that RAG-dependent stories in Epic 5 (chatbot) and Epic 7 (RCA agent) have a populated vector store from day one.

## Acceptance Criteria

1. **Given** service_webapp starts, **When** the Milvus Lite client initialises, **Then** it connects to the embedded Milvus Lite DB at `/app/data/milvus/sboai.db` (Podman volume `milvus_lite_data`). (ARCH-7)
2. **And** three collections are created **if not present**: `faq_chunks` (`chunk_id, text, embedding[1536], category, source_doc, plan_type`), `plan_vectors` (`plan_id, text, embedding[1536], plan_type, price, validity`), `sop_chunks` (`chunk_id, text, embedding[1536], rule_id, severity, domain`). (ARCH-8)
3. **And** each collection uses an **HNSW** index on `embedding` and is configured to support **BM25 + RRF hybrid search**. (ARCH-8)
4. **Given** `just seed-milvus` is run after `just seed`, **When** the seeding script executes, **Then** `plan_vectors` is populated from `plans_plans` (1,000 vectors via `text-embedding-3-small`, 1536 dims).
5. **And** `faq_chunks` is populated from a static FAQ YAML file (**minimum 50** entries).
6. **And** `sop_chunks` is populated from the `sop_knowledge_chunks` table.
7. **And** `just seed-milvus` is **idempotent** — it drops and re-creates the collections on re-run.

## Tasks / Subtasks

- [ ] **Task 1: `VectorStoreProtocol` port** (AC: #1, #2, #3)
  - [ ] Create `service_webapp/src/core/protocols/vector_store.py` — a `@runtime_checkable Protocol` mirroring the existing `DatabaseProtocol`/`CacheProtocol` style (async, minimal). Methods: `async ping() -> bool` (never raises), `async create_collections_if_absent() -> None`, `async upsert(collection, rows) -> None`, and (for Epic 5 consumers) `async hybrid_search(collection, query_text, query_embedding, *, filters=None, top_k=5) -> list[dict]`. [Source: service_webapp/src/core/protocols/{db,cache}.py; architecture.md#1.12.1 (VectorStoreProtocol seam, line 1047)]
- [ ] **Task 2: `MilvusAdapter`** (AC: #1, #2, #3)
  - [ ] Create `service_webapp/src/adapters/milvus.py` implementing `VectorStoreProtocol` over `pymilvus.MilvusClient(uri=settings.milvus_uri)`. `pymilvus[milvus-lite]>=2.4` is **already** in deps — do not add it. [Source: service_webapp/pyproject.toml (pymilvus[milvus-lite]>=2.4)]
  - [ ] **pymilvus is synchronous** (no async client). Wrap blocking calls with `await asyncio.to_thread(...)` so the adapter satisfies the async Protocol without blocking the event loop. `ping()` swallows all exceptions and returns bool (match `cache.py`). Add a best-effort `close()`. [Source: service_webapp/src/adapters/redis.py (ping never raises, close best-effort)]
  - [ ] `create_collections_if_absent()`: for each of the three collections, `if not client.has_collection(name): create`. Schema per AC #2 — PK (`chunk_id`/`plan_id`, VARCHAR holding the source UUID), `text` (VARCHAR, the embeddable text), `embedding` (FLOAT_VECTOR, **dim=1536**), plus the per-collection metadata scalar fields. Build an **HNSW** index on `embedding`. Configure the BM25/sparse path so hybrid search is possible (see hybrid-search note). [Source: epics.md#Story-2.7 (line 1038); architecture.md#1.7.5 (collection table), #1.6.1 (Dense HNSW + BM25 + RRF)]
- [ ] **Task 3: Config additions** (AC: #1, #4)
  - [ ] Add to `service_webapp/src/core/config.py` `Settings`: `milvus_uri: str = "/app/data/milvus/sboai.db"` (optional with default → matches the volume mount), and embedding config `embedding_model: str = "text-embedding-3-small"`, `embedding_dimensions: int = 1536`. Reuse the **existing** optional `azure_openai_api_key` / `azure_openai_endpoint` for the embedding client — do not add duplicate keys. [Source: service_webapp/src/core/config.py:40-100 (Settings, azure_openai_*); architecture.md#1.7.4 (MilvusClient uri="/app/data/milvus/sboai.db")]
- [ ] **Task 4: Lifespan wiring** (AC: #1)
  - [ ] In `service_webapp/src/main.py` lifespan, construct `MilvusAdapter(settings.milvus_uri)` into `app.state` if not injected (mirror the `db_adapter`/`cache_adapter` `getattr(... ) is None` idempotent pattern), call `create_collections_if_absent()` on startup, append to `owned`, and `close()` on shutdown. Add a Milvus `ping()` to the `/ready` health check alongside db/cache if that endpoint aggregates dependencies. [Source: service_webapp/src/main.py:62-95 (lifespan, owned adapters); 1-4 story (/ready aggregation)]
  - [ ] **⚠️ Single-process constraint:** Milvus Lite is in-process and single-writer; `docker/docker-compose.yaml` already pins `service_webapp` to `replicas: 1`. Do not open a second `MilvusClient` against the same `.db` file from another process (the seed script connects to the **same path** — run it while the app is stopped, or document that the embedded file is single-writer). [Source: architecture.md#1.7.4 (replicas:1, single-process); docker/docker-compose.yaml]
- [ ] **Task 5: Embedding client** (AC: #4, #5, #6)
  - [ ] Add a thin embedding helper that calls Azure OpenAI `text-embedding-3-small` (1536-dim) in **batches** (e.g. 100 texts/call). Reuse `settings.azure_openai_*`. Keep it injectable/mockable so seed tests don't hit the network. If an LLM/embedding client already exists under `adapters/`, extend it; otherwise add `adapters/embeddings.py`. [Source: architecture.md#1.6.1 (text-embedding-3-small); service_webapp/src/core/config.py (azure_openai_*)]
- [ ] **Task 6: Seed script `seed_milvus.sh` + Python seeder** (AC: #4, #5, #6, #7)
  - [ ] Create `scripts/seed_milvus.sh` (executable **bash** — see variance note) that invokes a Python seeder module. Replace the **stub** `seed-milvus` recipe in the root `justfile` (currently `@exit 1`) to call it. [Source: justfile (seed-milvus stub); architecture.md#1.12.2 (bash, not python)]
  - [ ] Seeder logic (idempotent — **drop then recreate** all three collections per AC #7, then populate):
    - `plan_vectors`: `SELECT id, plan_name, plan_code, price_paise, validity_days FROM plans_plans WHERE is_active = TRUE` → embed `plan_name`(+`plan_code`/description) → upsert with metadata `plan_id, plan_type, price (price_paise), validity (validity_days)`. Expect ~1,000 rows (seeded by Story 2.6). [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-122; 2-6 story (1K plans)]
    - `faq_chunks`: load a static FAQ YAML (**≥50** entries; see Task 7) → embed `question`+`answer` → upsert with metadata `category, source_doc, plan_type`.
    - `sop_chunks`: `SELECT id, chunk_text, source_document, domain FROM sop_knowledge_chunks` → embed `chunk_text` → upsert with metadata `rule_id (source_document), severity, domain`. Source rows are written by Story 2.6's `sop_generator.py`. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:571-583; 2-6 story (sop_generator)]
  - [ ] Log final per-collection counts; assert `plan_vectors == 1000`, `faq_chunks >= 50`, `sop_chunks > 0`. Build Postgres conninfo from `settings.db.*` (reuse the config singleton). [Source: service_webapp/src/core/config.py:40-100]
- [ ] **Task 7: Static FAQ YAML** (AC: #5)
  - [ ] Create a version-controlled FAQ data file (≥50 telecom self-care FAQs) — suggested `service_webapp/data/faq.yaml` with entries `{id, question, answer, category, source_doc, plan_type?}`. Document the chosen path. [Source: epics.md#Story-2.7 (line 1048)]
- [ ] **Task 8: Tests** (AC: #2, #3, #7)
  - [ ] Unit (mock `MilvusClient` + mock embedding client): `create_collections_if_absent` creates only absent collections with dim=1536 + HNSW; `ping()` returns bool and never raises; seeder maps DB/YAML rows → correct collection schema + metadata; re-run drops+recreates (idempotency). No network, no real Milvus. [Source: service_webapp test conventions; 2-5 story (mock-based unit matrix)]
  - [ ] Integration (`@pytest.mark.slow`): against a **real Milvus Lite** file in a tmp dir (it's embedded — no container needed), create collections and upsert a few fake-embedding rows, assert counts and that a re-run is clean. Mock embeddings (fixed 1536-float vectors) to avoid Azure calls. Add any new import to the tox env `deps`. [Source: 1-4 story (slow marker); 2-1 story (slow integration)]

## Dev Notes

### Scope boundary

- **DOES:** embed Milvus Lite in service_webapp (connect, three collections, HNSW + hybrid-search-ready), config + lifespan wiring, embedding helper, the `seed_milvus.sh` + Python seeder (plans/FAQ/SOP → vectors, idempotent drop+recreate), the static FAQ YAML, unit + one slow integration test.
- **DOES NOT:** generate the **relational** synthetic data (`plans_plans`, `sop_knowledge_chunks` rows come from Story 2.6 `just seed`), implement the **chatbot RAG query path** (Epic 5 consumes `hybrid_search`), or build any UI. `seed-milvus` runs **after** `seed`.

### 🚨 Hard dependency: run `just seed` (2.6) first

- `plan_vectors` reads `plans_plans` (needs the 1K plans from Story 2.6) and `sop_chunks` reads `sop_knowledge_chunks` (written by 2.6's `sop_generator.py`). If those tables are empty, the seeder produces near-empty collections. Make the script fail loudly (clear message) if `plans_plans` is empty so the ordering mistake is obvious. [Source: 2-6 story; epics.md#Story-2.7 (line 1042 "after just seed")]

### Hybrid search (BM25 + RRF) — config now, query later

- AC #3 requires the collections be **created so hybrid search is possible**; the actual hybrid query (dense HNSW + BM25 sparse, fused via RRF reranker) is exercised by Epic 5's `rag_search.py`. Native BM25/sparse-vector functions landed in **pymilvus 2.5**; with the pinned `>=2.4` you may need 2.5 for first-class `Function`-based BM25 + `RRFRanker`. **Check the resolved pymilvus version** at implementation time: if it's 2.5+, configure the BM25 function + sparse field now; if 2.4, create the dense HNSW collection and a sparse/scalar `text` field that a later BM25 index can attach to, and **note the limitation in Completion Notes** so Epic 5 knows the state. Do not block 2.7 on a full hybrid-query implementation. [Source: architecture.md#1.6.1 (RRF reranker), #1.7.5 (BM25 lexical index); service_webapp/pyproject.toml (pymilvus>=2.4)]

### Reuse the adapter/protocol DI convention (don't reinvent)

- Existing adapters (`postgres.py` → `Psycopg3AsyncAdapter`, `redis.py` → `ValkeyAdapter`, `cognito.py`) implement `core/protocols/*` ports and are wired in `main.py` lifespan into `app.state`. The Milvus adapter follows the **identical** shape: a Protocol in `core/protocols/vector_store.py`, the impl in `adapters/milvus.py`, construction in lifespan. This keeps tests able to inject a fake. [Source: service_webapp/src/adapters/{postgres,redis}.py; src/core/protocols/{db,cache}.py; src/main.py:62-125; architecture.md#1.12.1]

### Money & dims are integers/fixed

- `plan_vectors.price` carries `price_paise` (integer paise, not rupees). `embedding` dim is **exactly 1536** (text-embedding-3-small). Both are fixed by ARCH-8. [Source: architecture.md#1.7.5, #1.12.2 (paise)]

### Script location & invocation

- **Variance (same as 2.6):** architecture §1.12.2 once wrote `python scripts/seed_milvus.sh` (running a `.sh` via python — wrong); the corrected convention (and the `justfile` stub) is a **bash** `scripts/seed_milvus.sh` that internally runs the Python seeder with `PYTHONPATH=src`. Follow bash. If a bare `scripts/` file can't import `core.config`, run the Python seeder with `cd service_webapp && PYTHONPATH=src python -m ...` from inside the shell script, or place the seeder under `service_webapp/`. Document the final layout. [Source: justfile (seed-milvus stub); architecture.md#1.12.2]

### Config singleton — reuse, fail-fast

- `from core.config import settings` → `settings.milvus_uri`, `settings.db.*`, `settings.azure_openai_*`. Eager singleton; missing required vars fail at import. Embedding calls require `azure_openai_api_key`/`endpoint` to be set in the seed environment. [Source: service_webapp/src/core/config.py:40-100]

### Testing standards summary

- `uv tox` `lint` (ruff + ruff format --check + pyrefly) + `test` (pytest `-m "not slow"`). Unit tests mock both `MilvusClient` and the embedding client (no network, no real vector store). The one `slow` test uses a **real embedded Milvus Lite file in a tmp dir** (no testcontainers needed — it's in-process) with deterministic fake embeddings. ruff 120 / py311. Add new imports to tox env `deps`. [Source: service_webapp/pyproject.toml; 1-4 story; 2-1 story]

### Project Structure Notes

- **NEW:** `service_webapp/src/core/protocols/vector_store.py`, `service_webapp/src/adapters/milvus.py`, embedding helper (`adapters/embeddings.py` or extend existing), `scripts/seed_milvus.sh` + Python seeder, `service_webapp/data/faq.yaml`, tests under `service_webapp/tests/`.
- **MODIFIES:** `service_webapp/src/core/config.py` (milvus_uri + embedding config), `service_webapp/src/main.py` (lifespan + `/ready`), root `justfile` (`seed-milvus`: stub → real), `service_webapp/pyproject.toml` (embedding/yaml deps + tox env deps if needed; pymilvus already present).
- **Already in place — do not redo:** `pymilvus[milvus-lite]>=2.4` dependency; the `milvus_lite_data` volume mounted at `/app/data/milvus`; `replicas: 1`. [Source: service_webapp/pyproject.toml; docker/docker-compose.yaml]

### References

- [Source: epics.md#Story-2.7 (lines 1022-1052); ARCH-7, ARCH-8 (epics.md lines 238,240)]
- [Source: architecture.md#1.7.4 (Milvus Lite deployment: uri="/app/data/milvus/sboai.db", replicas:1), #1.7.5 (three collections, HNSW, BM25), #1.6.1 (dense + BM25 + RRF hybrid), #1.12.1 (VectorStoreProtocol/MilvusAdapter seam), #1.12.2 (seed-milvus recipe)]
- [Source: service_webapp/pyproject.toml (pymilvus[milvus-lite]>=2.4)]
- [Source: service_webapp/src/core/config.py:40-100 (settings, azure_openai_*), src/main.py:62-125 (lifespan), src/core/protocols/{db,cache}.py, src/adapters/{postgres,redis}.py]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-122 (plans), 571-583 (sop_knowledge_chunks)]
- [Source: docker/docker-compose.yaml (milvus_lite_data volume, replicas:1)]
- [Source: 2-6 story (plans + sop_knowledge_chunks seeded by `just seed`), 1-4 story (lifespan/ready, testcontainers), 2-1 story (slow integration, reuse settings)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
