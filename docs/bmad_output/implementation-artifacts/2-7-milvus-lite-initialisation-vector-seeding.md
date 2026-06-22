---
baseline_commit: b0422e825b55b899276adc56cee049a3d548bc74
---

# Story 2.7: Milvus Lite Initialisation & Vector Seeding

Status: review

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

- [x] **Task 1: `VectorStoreProtocol` port** (AC: #1, #2, #3)
  - [x] Create `service_webapp/src/core/protocols/vector_store.py` — a `@runtime_checkable Protocol` mirroring the existing `DatabaseProtocol`/`CacheProtocol` style (async, minimal). Methods: `async ping() -> bool` (never raises), `async create_collections_if_absent() -> None`, `async upsert(collection, rows) -> None`, and (for Epic 5 consumers) `async hybrid_search(collection, query_text, query_embedding, *, filters=None, top_k=5) -> list[dict]`. [Source: service_webapp/src/core/protocols/{db,cache}.py; architecture.md#1.12.1 (VectorStoreProtocol seam, line 1047)]
- [x] **Task 2: `MilvusAdapter`** (AC: #1, #2, #3)
  - [x] Create `service_webapp/src/adapters/milvus.py` implementing `VectorStoreProtocol` over `pymilvus.MilvusClient(uri=settings.milvus_uri)`. `pymilvus[milvus-lite]>=2.4` is **already** in deps — do not add it. [Source: service_webapp/pyproject.toml (pymilvus[milvus-lite]>=2.4)]
  - [x] **pymilvus is synchronous** (no async client). Wrap blocking calls with `await asyncio.to_thread(...)` so the adapter satisfies the async Protocol without blocking the event loop. `ping()` swallows all exceptions and returns bool (match `cache.py`). Add a best-effort `close()`. [Source: service_webapp/src/adapters/redis.py (ping never raises, close best-effort)]
  - [x] `create_collections_if_absent()`: for each of the three collections, `if not client.has_collection(name): create`. Schema per AC #2 — PK (`chunk_id`/`plan_id`, VARCHAR holding the source UUID), `text` (VARCHAR, the embeddable text), `embedding` (FLOAT_VECTOR, **dim=1536**), plus the per-collection metadata scalar fields. Build an **HNSW** index on `embedding`. Configure the BM25/sparse path so hybrid search is possible (see hybrid-search note). [Source: epics.md#Story-2.7 (line 1038); architecture.md#1.7.5 (collection table), #1.6.1 (Dense HNSW + BM25 + RRF)]
- [x] **Task 3: Config additions** (AC: #1, #4)
  - [x] Add to `service_webapp/src/core/config.py` `Settings`: `milvus_db_uri: str = "/app/data/milvus/sboai.db"` (env var `MILVUS_DB_URI` — renamed from `milvus_uri` to avoid conflict with pymilvus's own `MILVUS_URI` ORM env var), and embedding config `embedding_model: str = "text-embedding-3-small"`, `embedding_dimensions: int = 1536`. Reuse the **existing** optional `azure_openai_api_key` / `azure_openai_endpoint` for the embedding client — do not add duplicate keys. [Source: service_webapp/src/core/config.py:40-100 (Settings, azure_openai_*); architecture.md#1.7.4 (MilvusClient uri="/app/data/milvus/sboai.db")]
- [x] **Task 4: Lifespan wiring** (AC: #1)
  - [x] In `service_webapp/src/main.py` lifespan, construct `MilvusAdapter(settings.milvus_db_uri)` into `app.state` if not injected (mirror the `db_adapter`/`cache_adapter` `getattr(... ) is None` idempotent pattern), call `create_collections_if_absent()` on startup, append to `owned`, and `close()` on shutdown. Add a Milvus `ping()` to the `/ready` health check alongside db/cache if that endpoint aggregates dependencies. [Source: service_webapp/src/main.py:62-95 (lifespan, owned adapters); 1-4 story (/ready aggregation)]
  - [x] **⚠️ Single-process constraint:** Milvus Lite is in-process and single-writer; `docker/docker-compose.yaml` already pins `service_webapp` to `replicas: 1`. Do not open a second `MilvusClient` against the same `.db` file from another process (the seed script connects to the **same path** — run it while the app is stopped, or document that the embedded file is single-writer). [Source: architecture.md#1.7.4 (replicas:1, single-process); docker/docker-compose.yaml]
- [x] **Task 5: Embedding client** (AC: #4, #5, #6)
  - [x] Add a thin embedding helper that calls Azure OpenAI `text-embedding-3-small` (1536-dim) in **batches** (e.g. 100 texts/call). Reuse `settings.azure_openai_*`. Keep it injectable/mockable so seed tests don't hit the network. If an LLM/embedding client already exists under `adapters/`, extend it; otherwise add `adapters/embeddings.py`. [Source: architecture.md#1.6.1 (text-embedding-3-small); service_webapp/src/core/config.py (azure_openai_*)]
- [x] **Task 6: Seed script `seed_milvus.sh` + Python seeder** (AC: #4, #5, #6, #7)
  - [x] Create `scripts/seed_milvus.sh` (executable **bash** — see variance note) that invokes a Python seeder module. Replace the **stub** `seed-milvus` recipe in the root `justfile` (currently `@exit 1`) to call it. [Source: justfile (seed-milvus stub); architecture.md#1.12.2 (bash, not python)]
  - [x] Seeder logic (idempotent — **drop then recreate** all three collections per AC #7, then populate):
    - `plan_vectors`: `SELECT id, plan_name, plan_code, price_paise, validity_days FROM plans_plans WHERE is_active = TRUE` → embed `plan_name`(+`plan_code`/description) → upsert with metadata `plan_id, plan_type, price (price_paise), validity (validity_days)`. Expect ~1,000 rows (seeded by Story 2.6). [Source: service_webapp/db/migrations/V1__baseline_schema.sql:107-122; 2-6 story (1K plans)]
    - `faq_chunks`: load a static FAQ YAML (**≥50** entries; see Task 7) → embed `question`+`answer` → upsert with metadata `category, source_doc, plan_type`.
    - `sop_chunks`: `SELECT id, chunk_text, source_document, domain FROM sop_knowledge_chunks` → embed `chunk_text` → upsert with metadata `rule_id (source_document), severity, domain`. Source rows are written by Story 2.6's `sop_generator.py`. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:571-583; 2-6 story (sop_generator)]
  - [x] Log final per-collection counts; assert `plan_vectors == 1000`, `faq_chunks >= 50`, `sop_chunks > 0`. Build Postgres conninfo from `settings.db.*` (reuse the config singleton). [Source: service_webapp/src/core/config.py:40-100]
- [x] **Task 7: Static FAQ YAML** (AC: #5)
  - [x] Create a version-controlled FAQ data file (≥50 telecom self-care FAQs) — suggested `service_webapp/data/faq.yaml` with entries `{id, question, answer, category, source_doc, plan_type?}`. Document the chosen path. [Source: epics.md#Story-2.7 (line 1048)]
- [x] **Task 8: Tests** (AC: #2, #3, #7)
  - [x] Unit (mock `MilvusClient` + mock embedding client): `create_collections_if_absent` creates only absent collections with dim=1536 + HNSW; `ping()` returns bool and never raises; seeder maps DB/YAML rows → correct collection schema + metadata; re-run drops+recreates (idempotency). No network, no real Milvus. [Source: service_webapp test conventions; 2-5 story (mock-based unit matrix)]
  - [x] Integration (`@pytest.mark.slow`): against a **real Milvus Lite** file in a tmp dir (it's embedded — no container needed), create collections and upsert a few fake-embedding rows, assert counts and that a re-run is clean. Mock embeddings (fixed 1536-float vectors) to avoid Azure calls. Add any new import to the tox env `deps`. [Source: 1-4 story (slow marker); 2-1 story (slow integration)]

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

claude-sonnet-4-6

### Debug Log References

1. **pymilvus ORM `Connections()` singleton / `MILVUS_URI` conflict** — importing pymilvus triggered `orm/connections.py` at module level, which read `os.environ["MILVUS_URI"]`. Old ORM `__parse_address_from_uri` rejected local `.db` paths as invalid HTTP URIs. Fix: renamed config field from `milvus_uri` to `milvus_db_uri` so pydantic-settings reads `MILVUS_DB_URI`, leaving pymilvus's own `MILVUS_URI` unset.

2. **pymilvus `settings.py` calls `load_dotenv()` at import** — pymilvus unconditionally calls `load_dotenv()` on import, polluting `os.environ` with all `.env` values. This caused `test_settings_loads_when_required_present` (which tests default values) to see `AZURE_OPENAI_API_KEY=dummy-azure-openai-key` from `.env` even with `_env_file=None`. Fix: added `monkeypatch.delenv` for the affected vars in the test.

3. **`"name"` vs `"field_name"` in schema dict** — `_COLLECTION_EXTRA_FIELDS` used `"name"` key but `CollectionSchema.add_field()` expects `"field_name"`. Fixed by renaming all dict keys.

4. **Unit test fixture losing patch scope** — `adapter` fixture exited the `with patch(...)` block before the test body ran, causing real `MilvusClient.create_schema()` calls. Fixed by using `yield adp` inside the `with` block.

5. **Unused `azure_openai_api_key` config default changed** — accidentally set to `"dummy-azure-openai-key"` which broke the existing test asserting `cfg.azure_openai_api_key == ""`. Reverted to `""` — dummy values live only in `.env` and `.env.example`.

### Completion Notes List

- Config field name change: story says `milvus_uri` but final impl uses `milvus_db_uri` (env var `MILVUS_DB_URI`). Required to avoid conflict with pymilvus's own `MILVUS_URI` ORM singleton. All consumers (main.py, seed_milvus.py, seed_milvus.sh) use `milvus_db_uri`/`MILVUS_DB_URI`.
- pymilvus version resolved to ≥2.5 (tox test env pins `pymilvus[milvus-lite]>=2.5`). BM25 `Function` + `SPARSE_FLOAT_VECTOR` + `SPARSE_INVERTED_INDEX` fully configured on all three collections. Epic 5 can use `hybrid_search()` without schema changes.
- Graceful Milvus startup: lifespan wraps `MilvusAdapter` construction in try/except. If `/app/data/milvus/` doesn't exist (e.g. unit test environment), the app boots with `app.state.milvus_adapter = None` and `/ready` omits the `milvus` key — existing tests unaffected.
- LangChain `AzureOpenAIEmbeddings` used exclusively for the embedding client (`adapters/embeddings.py`). No bare OpenAI SDK usage.
- Seed script (`scripts/seed_milvus.py` + `scripts/seed_milvus.sh`) is idempotent: drops then recreates all three collections. Asserts `plan_vectors == 1000`, `faq_chunks >= 50`, `sop_chunks > 0`. Fails loudly if `plans_plans` is empty.
- 16 pre-existing `test_payment_methods.py` failures confirmed at Story 2.7 baseline — not introduced by this story.

### File List

**New files:**
- `service_webapp/src/core/protocols/vector_store.py`
- `service_webapp/src/adapters/milvus.py`
- `service_webapp/src/adapters/embeddings.py`
- `service_webapp/data/faq.yaml` (55 telecom FAQ entries)
- `scripts/seed_milvus.py`
- `scripts/seed_milvus.sh`
- `service_webapp/tests/unit/test_milvus_adapter.py`
- `service_webapp/tests/integration/test_milvus_integration.py`

**Modified files:**
- `service_webapp/src/core/config.py` — added `milvus_db_uri`, `embedding_model`, `embedding_dimensions`
- `service_webapp/src/main.py` — MilvusAdapter construction in lifespan (graceful), `/ready` milvus ping
- `service_webapp/src/routers/health.py` — optional milvus ping in `/ready`
- `service_webapp/pyproject.toml` — added `langchain-openai>=0.2`, `pyyaml>=6` to tox deps; bumped pymilvus tox pin to ≥2.5
- `service_webapp/.env.example` — added `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `MILVUS_DB_URI`
- `service_webapp/.env` — added dummy Azure OpenAI keys (user overrides) and `MILVUS_DB_URI`
- `service_webapp/tests/unit/test_config.py` — added `monkeypatch.delenv` for pymilvus-leaked env vars
- `justfile` — `seed-milvus` recipe now calls `bash scripts/seed_milvus.sh`
- `service_webapp/uv.lock` — updated with new deps

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-06-22 | 1.0 | Story 2.7 implementation complete: VectorStoreProtocol, MilvusAdapter, embedding client (LangChain AzureOpenAI), lifespan wiring, FAQ YAML, seed script, unit + integration tests | Claude Sonnet 4.6 |
