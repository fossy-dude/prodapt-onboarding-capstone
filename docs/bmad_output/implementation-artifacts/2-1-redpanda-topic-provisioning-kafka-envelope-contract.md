---
baseline_commit: 75578fdd40c9bf8c8aac24a2c8e366220cfe4b6d
---

# Story 2.1: Redpanda Topic Provisioning & Kafka Envelope Contract

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want all Redpanda topics created with correct partition counts and a standard event envelope enforced across producers,
so that all pipeline components can communicate reliably and every event is traceable.

## Acceptance Criteria

1. **Given** Redpanda is running via Podman Compose, **When** `just up` completes, **Then** the following topics exist with the specified partition counts: `cdr.raw` (24p), `cdr.enriched.filtered` (24p), `cdr.fraud.flagged` (6p), `fraud.alerts` (6p), `notification.events` (12p), `cdr.dlq` (6p) (ARCH-10).
2. A topic provisioning script `cdr-pipeline/scripts/provision_topics.py` creates the topics **idempotently** — safe to re-run; existing topics are left untouched (no error, no partition change).
3. The Kafka event envelope is defined as a shared Pydantic v2 model with exactly these fields: `event_type: str`, `event_id: UUID` (UUIDv7), `trace_id: str`, `timestamp: datetime` (UTC, ISO-8601), `payload: dict` (ARCH-11).
4. A producer helper serialises the envelope so that **both** representations of the trace are present on every message: `traceparent` in the Kafka **message header** AND `trace_id` in the **JSON body** (ARCH-11, NFR-17).
5. The `cdr.raw` topic uses **key = `subscriber_id`** (UTF-8 bytes) so all events for one subscriber land on the same partition (per-subscriber ordering).
6. `just up` (and the standalone recipe) invoke provisioning after Redpanda is healthy; a `just provision-topics` recipe runs the script on demand. The script logs each topic as `created` or `exists`.

## Tasks / Subtasks

- [x] **Task 1: Define the shared Kafka event envelope model** (AC: #3)
  - [x] Create `cdr-pipeline/src/models/__init__.py` and `cdr-pipeline/src/models/envelope.py`
  - [x] `class EventEnvelope(BaseModel)` with fields `event_type: str`, `event_id: UUID`, `trace_id: str`, `timestamp: datetime`, `payload: dict[str, Any]`. Use `model_config = ConfigDict(...)` per pydantic v2; serialise `event_id` as `str`, `timestamp` as ISO-8601 UTC.
  - [x] Add a factory `EventEnvelope.new(event_type, payload, trace_id, *, event_id=None, timestamp=None)` that defaults `event_id` to a fresh **UUIDv7** (use the `uuid7` package — add `uuid7>=0.1` to deps) and `timestamp` to `datetime.now(UTC)`. Do NOT call `uuid4`.
  - [x] Add the CDR payload schema `cdr-pipeline/src/models/cdr.py` mirroring `billing_cdr_events` columns (CORE + voice/sms/data variants). Validate `cdr_type ∈ {voice, sms, data}`, `cost_paise: int`, MSISDNs as strings. This is the schema Story 2.2 validates against. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:177-209]
- [x] **Task 2: Implement the producer helper with dual trace propagation** (AC: #4, #5)
  - [x] Create `cdr-pipeline/src/adapters/kafka.py` with an aiokafka `AIOKafkaProducer` wrapper (async; `kafka_brokers` from `settings`).
  - [x] `async publish(topic, *, key, envelope)` serialises the envelope to JSON (UTF-8) as the value, sets `key` to `subscriber_id` bytes, and injects a W3C `traceparent` header built from `envelope.trace_id` into the Kafka message headers. Body already carries `trace_id`.
  - [x] Expose a `MessageBrokerProtocol` in `cdr-pipeline/src/core/protocols/broker.py` (typed Protocol, async) so the consumer/screener depend on the interface, mirroring the existing `DatabaseProtocol`/`CacheProtocol` DI convention. [Source: architecture.md#1.12.1 (Protocol interfaces, async-only — ARCH-15)]
- [x] **Task 3: Implement the idempotent provisioning script** (AC: #1, #2, #6)
  - [x] Create `cdr-pipeline/scripts/provision_topics.py`. Use the aiokafka admin client (`aiokafka.admin.AIOKafkaAdminClient`) — or `kafka-python`'s `KafkaAdminClient` if the aiokafka admin surface is insufficient; prefer aiokafka to avoid a new dep.
  - [x] Define the topic spec as a module-level list of `(name, partitions, replication_factor=1)`: `cdr.raw`/24, `cdr.enriched.filtered`/24, `cdr.fraud.flagged`/6, `fraud.alerts`/6, `notification.events`/12, `cdr.dlq`/6. (ARCH-10)
  - [x] List existing topics first; create only the missing ones (`create_topics` with the existing-topic error swallowed). Log `created`/`exists` per topic. Re-running must be a no-op. Connect via `settings.kafka_brokers`.
- [x] **Task 4: Wire provisioning into compose / justfile** (AC: #1, #6)
  - [x] Add `provision-topics` recipe to the root `justfile` (pattern: `cd cdr-pipeline && PYTHONPATH=src python scripts/provision_topics.py`), matching the cross-platform `{{ justfile_directory() }}` convention used by `provision-cognito`.
  - [x] Ensure provisioning runs after Redpanda is healthy on `just up` — either append the recipe call to `up`, or add a short-lived `provision-topics` service to `docker/docker-compose.yaml` (depends_on redpanda: service_healthy, `restart: no`), consistent with how the `flyway` runner is wired. Document the chosen approach in Completion Notes. [Source: 1-2 story (flyway short-lived runner pattern); 1-3 story (justfile recipes)]
- [x] **Task 5: Tests** (AC: #2, #3, #4)
  - [x] Unit: `EventEnvelope.new()` produces a UUIDv7 `event_id` (version nibble == 7), UTC timestamp, and round-trips through `model_dump_json()`/`model_validate_json()`.
  - [x] Unit: the producer helper sets `traceparent` header AND a body `trace_id` equal to the envelope's `trace_id`; key is the `subscriber_id` bytes. Mock the `AIOKafkaProducer` (no live broker).
  - [x] Integration (`@pytest.mark.slow`/`integration`, testcontainers Redpanda/Kafka): running `provision_topics.py` twice yields the 6 topics with correct partition counts and the second run is a clean no-op. Use `DOCKER_HOST=unix:///run/user/1000/podman/podman.sock` (rootless podman). [Source: 1-4 debug log]

### Review Findings

- [x] [Review][Patch] Provisioning masks partition-count mismatches on the "exists" path [cdr-pipeline/scripts/provision_topics.py:142-165] — CRITICAL
- [x] [Review][Patch] EventEnvelope.timestamp serializer silently converts naive datetimes as system-local time [cdr-pipeline/src/models/envelope.py:515-518] — HIGH
- [x] [Review][Patch] payload: dict[str, Any] silently coerces non-JSON-serializable types [cdr-pipeline/src/models/envelope.py:509] — HIGH
- [x] [Review][Patch] build_traceparent accepts malformed trace_id and emits invalid W3C header [cdr-pipeline/src/adapters/kafka.py:242-250] — HIGH
- [x] [Review][Patch] build_traceparent can produce all-zero span_id [cdr-pipeline/src/adapters/kafka.py:249] — HIGH
- [x] [Review][Patch] _serialise_timestamp comment lies (emits +00:00, not Z) [cdr-pipeline/src/models/envelope.py:515-518] — MEDIUM
- [x] [Review][Patch] provision_topics has no timeout [cdr-pipeline/scripts/provision_topics.py:136 + justfile:982-983,1005-1006] — MEDIUM
- [x] [Review][Patch] Network blip mid-create_topics leaves partial state [cdr-pipeline/scripts/provision_topics.py:158-194] — MEDIUM
- [x] [Review][Patch] just up/deps fails whole stack on provisioning error [justfile:982-983,1005-1006] — MEDIUM
- [x] [Review][Patch] KafkaProducer.publish with key=None raises AttributeError [cdr-pipeline/src/adapters/kafka.py:298] — MEDIUM
- [x] [Review][Patch] KafkaProducer.start() race [cdr-pipeline/src/adapters/kafka.py:267-272] — MEDIUM
- [x] [Review][Patch] CdrBase.cost_paise has no upper bound [cdr-pipeline/src/models/cdr.py:423] — MEDIUM
- [x] [Review][Patch] VoiceCdr.duration_seconds uncapped, DataCdr volume precision mismatch [cdr-pipeline/src/models/cdr.py:435,452-454] — MEDIUM
- [x] [Review][Patch] MSISDN fields accept non-E.164 strings [cdr-pipeline/src/models/cdr.py:432-433] — LOW
- [x] [Review][Patch] EventEnvelope.trace_id has no max-length constraint [cdr-pipeline/src/models/envelope.py:507] — LOW
- [x] [Review][Patch] settings.kafka_brokers accepts empty string [cdr-pipeline/src/core/config.py] — LOW
- [x] [Review][Defer] Provisioning swallows only TopicAlreadyExistsError — other errors propagate [cdr-pipeline/scripts/provision_topics.py:158-165] — deferred, design choice
- [x] [Review][Defer] Missing clearer error messaging for Kafka connection failures [cdr-pipeline/scripts/provision_topics.py:136] — deferred, enhancement
- [x] [Review][Defer] main() doesn't expose --brokers CLI flag [cdr-pipeline/scripts/provision_topics.py:187] — deferred, UX enhancement

## Dev Notes

### Scope boundary

- **DOES:** the 6 topics provisioned idempotently with exact partition counts; the shared `EventEnvelope` Pydantic model + CDR payload schema; an async producer helper that guarantees `traceparent` header + body `trace_id`; justfile/compose wiring; unit + one integration test.
- **DOES NOT:** consume from any topic (Story 2.2), deduct balance (2.3), write audit rows (2.4), or build admin endpoints (2.5). No CDR simulator/producer UI (Story 2.8). This story establishes the **contract and the topics**, not the consumers.

### Where the code lives — `cdr-pipeline` is a real but near-empty codebase

- `cdr-pipeline/` currently contains only `src/core/config.py` (the eager `settings` singleton), `src/main.py` (stub), and tests. **You are building the pipeline package out from here.** Follow the planned source tree in architecture §1.12.1:
  - `src/models/` — shared envelope + CDR schema (this story)
  - `src/adapters/kafka.py`, `src/adapters/postgres.py`, `src/adapters/redis.py` — async adapters
  - `src/core/protocols/{broker,db,cache}.py` — typed Protocols
  - `src/consumer/`, `src/dlq/`, `src/screener/`, `src/management/` — later stories
- [Source: architecture.md#1.12.1 (cdr-pipeline layout, lines 1006-1030); cdr-pipeline/src/core/config.py]

### Config singleton — already present, reuse it

- `from core.config import settings` gives `settings.kafka_brokers`, `settings.valkey_url`, `settings.db.*`, `settings.kafka_consumer_group` ("cdr-pipeline"), `settings.otel_service_name`. It eager-loads and fails fast on missing required vars. `pytest-env` already injects `KAFKA_BROKERS=localhost:9092` etc. for collection. Do not introduce a second settings object. [Source: cdr-pipeline/src/core/config.py:28-50; cdr-pipeline/pyproject.toml:226-234]

### Envelope contract is canonical and shared by two codebases (no shared package)

- MVP has **two separate codebases** — `cdr-pipeline/` and `service_webapp/` — that communicate **only via Kafka and Postgres, never HTTP**. There is no shared Python package. The CDR producer in `service_webapp` (the Story 2.8 simulator dispatch API) must emit the **identical** envelope. [Source: architecture.md#1.5.1 (two-codebase MVP, no inter-service HTTP)]
- **Decision:** define the canonical `EventEnvelope` here in `cdr-pipeline/src/models/envelope.py`. When Story 2.8 wires the simulator's producer in `service_webapp`, it must mirror this exact field set and dual-trace rule. Flag this duplication risk in Completion Notes so the reviewer/2.8 keep the two copies byte-compatible (consider a tiny copied module rather than divergent definitions).

### Trace propagation rule (NFR-17) — the high-value, easy-to-miss requirement

- **Every** Kafka message must carry the trace two ways: a W3C `traceparent` entry in the message **headers** AND `trace_id` in the JSON **body**. Downstream stages (2.2 enrich, 2.4 fraud/notification) re-propagate it; the audit row (2.4) stores it. Build the producer helper so a caller cannot publish without supplying `trace_id`. [Source: epics.md#Story-2.1 (line 870); architecture.md#1.11.4 (line 863); NFR-17]
- The OTEL middleware in `service_webapp` already extracts/sets `traceparent` and `request.state.trace_id` (Story 1.4). The CDR pipeline consumer (2.2) will `opentelemetry.propagate.extract(headers)` to continue the trace. Keep the header format W3C-compatible. [Source: 1-4 story (`core/middleware.py`); architecture.md#1.12.1 (OTEL middleware)]

### UUIDv7 for `event_id`

- Transactional/high-rate IDs are UUIDv7 (time-ordered, B-tree locality); reference tables use UUIDv4. `event_id` and `billing_cdr_events.id` are UUIDv7. Use the `uuid7` package (already used by `service_webapp`, version `uuid7>=0.1`); Postgres generates `billing_cdr_events.id` via `uuid_generate_v7()` (the `pg_uuidv7` extension, created once in `docker/postgres/init/01_extensions.sql` — do NOT `CREATE EXTENSION` in app code). [Source: architecture.md#1.7.1 (UUID strategy); service_webapp/pyproject.toml (uuid7>=0.1); 1-2 story (extensions in init scripts)]

### Topic & partition specifics (ARCH-10)

| Topic | Partitions | Key | Primary consumer (later stories) |
|-------|-----------|-----|----------------------------------|
| `cdr.raw` | 24 | `subscriber_id` | cdr-pipeline consumer (2.2) |
| `cdr.enriched.filtered` | 24 | `subscriber_id` | fraud pre-screener, notification (2.2 output) |
| `cdr.fraud.flagged` | 6 | `msisdn` | fraud-detection-agent (Epic 6) |
| `fraud.alerts` | 6 | `msisdn` | fraud dashboard, notification (Epic 6) |
| `notification.events` | 12 | `msisdn` | notification-service (Epic 4) |
| `cdr.dlq` | 6 | `cdr_id` | DLQ inspector (2.5) |

- 24 partitions on `cdr.raw`/`cdr.enriched.filtered` enables 24 parallel consumers (Story 2.2). Replication factor = 1 for single-broker MVP Redpanda. [Source: epics.md#Story-2.1; architecture.md#1.7.6, #1.4.1]

### Redpanda is already in compose

- `redpanda` service exists in `docker/docker-compose-dependencies.yaml` (Kafka-wire-compatible, no ZooKeeper) with a `rpk cluster health` healthcheck. aiokafka talks to it unchanged. Redpanda auto-creates topics on first produce, but **explicit provisioning with fixed partition counts is required** — auto-created topics default to 1 partition and would silently break the 24-way parallelism. [Source: 1-2 story (redpanda compose service); architecture.md#1.3.1]

### Async-only (ARCH-15)

- All I/O is async: `aiokafka` producer/admin, `psycopg` async pool, `valkey[asyncio]`. No blocking calls. Routes (later) are `async def`. Add `aiokafka>=0.11` to `cdr-pipeline/pyproject.toml` runtime deps and to the `lint`/`test` tox env `deps` (this codebase pins per-env deps explicitly — see its pyproject). [Source: architecture.md#1.12.1 (ARCH-15); cdr-pipeline/pyproject.toml:277-296]

### Testing standards summary

- `uv tox` (tox-uv) with `lint` (ruff + ruff format --check + pyrefly) and `test` (pytest, `-m "not slow"`) envs — identical to `service_webapp`. Unit tests need no broker; the one integration test uses testcontainers Kafka/Redpanda and is marked `slow`. ruff line-length 120, target py311, numpy docstrings. Add any new runtime import (`aiokafka`, `uuid7`) to the relevant tox env `deps` or lint/type/collect will fail. [Source: cdr-pipeline/pyproject.toml; 1-3 story (lint template); 1-4 story (testcontainers + rootless podman)]

### Project Structure Notes

- **NEW:** `cdr-pipeline/src/models/{__init__,envelope,cdr}.py`, `cdr-pipeline/src/adapters/kafka.py`, `cdr-pipeline/src/core/protocols/broker.py`, `cdr-pipeline/scripts/provision_topics.py`, tests under `cdr-pipeline/tests/unit/` + `cdr-pipeline/tests/integration/`.
- **EXTENDS:** root `justfile` (add `provision-topics`); optionally `docker/docker-compose.yaml` (short-lived provisioning service); `cdr-pipeline/pyproject.toml` (deps + tox env deps).
- **Variance — epic AC path:** Story 2.2's epic text names `cdr-pipeline/src/pipeline/consumer.py`/`pipeline/dedup.py`, but architecture §1.12.1 specifies `src/consumer/batch_processor.py` + `src/consumer/dedup.py`. Follow the **architecture** source tree (`consumer/`), not the epic's `pipeline/` path. This story creates only `models/`, `adapters/`, `core/protocols/`, `scripts/` — flagged here so the consumer (2.2) lands in the right place.
- **Variance — service name:** architecture says `service_backend`; the actual repo dir is `service_webapp` (the resolved project convention). Use `service_webapp`.

### References

- [Source: epics.md#Story-2.1 (lines 850-873)]
- [Source: architecture.md#1.7.6 (Kafka topics, ARCH-10)]
- [Source: architecture.md#1.11.4 (event envelope, traceparent + trace_id, ARCH-11, lines 849-863)]
- [Source: architecture.md#1.4.1 (CDR consumer pool, partitions)]
- [Source: architecture.md#1.12.1 (cdr-pipeline source tree, ARCH-15, lines 1006-1030)]
- [Source: architecture.md#1.5.1 (two-codebase MVP, no inter-service HTTP)]
- [Source: architecture.md#1.7.1 (UUIDv7 strategy)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:177-209 (billing_cdr_events columns)]
- [Source: cdr-pipeline/src/core/config.py (settings singleton); cdr-pipeline/pyproject.toml (tox/ruff/pytest)]
- [Source: 1-2 story (redpanda + flyway compose), 1-3 story (justfile + lint), 1-4 story (OTEL middleware + testcontainers)]

## Dev Agent Record

### Agent Model Used

Claude (GLM-5.2) via `bmad-dev-story` workflow.

### Debug Log References

- **uuid7 import bug in partial dev work:** the pre-existing `envelope.py` used `import uuid7 as _uuid7` / `_uuid7.uuid7()`, but the `uuid7>=0.1` PyPI package installs under the module name **`uuid_extensions`** (`from uuid_extensions import uuid7`). `import uuid7` raised `ModuleNotFoundError`, so `test_envelope.py` failed at collection. Fixed to `from uuid_extensions import uuid7`; `uuid7()` returns a `UUID` at runtime (its stub is the broad `Union[UUID, str, int, bytes]`, hence the `cast` in `EventEnvelope.new`). Confirmed against the installed `uuid7==0.1.0` (`top_level.txt = uuid_extensions`).
- **Live verification against the running stack:** Redpanda was already up on `localhost:9092`, so `provision_topics.py` was exercised directly. Run 1 created all 6 topics; run 2 reported every topic `exists` (idempotent no-op). `describe_topics` (keys: `topic`, `partitions`) confirmed exact partition counts `24/24/6/6/12/6` @ RF=1 on the broker.
- **testcontainers 429:** the default `RedpandaContainer` image (`docker.redpanda.com/redpandadata/redpanda:v23.1.13`) hit an unauthenticated Docker Hub rate limit (429). Pinned the fixture to the compose stack's already-cached image `docker.io/redpandadata/redpanda:v24.2.1` — matches the version under test and avoids the pull.
- **pyrefly vs pydantic discriminated union:** the canonical pydantic discriminator pattern (base declares the discriminator; variants narrow it) trips pyrefly `bad-override-mutable-attribute`. Resolved by declaring `cdr_type` per-variant only (removed from `CdrBase`); pydantic discrimination is unchanged. Separately, `UUID`/`datetime` cannot move behind `TYPE_CHECKING` in pydantic model modules (verified: raises `PydanticUserError: not fully defined`) — those imports are suppressed with `# noqa: TC003`, while the truly annotation-only `EventEnvelope` imports in `adapters/kafka.py` and `core/protocols/broker.py` were moved into `TYPE_CHECKING` blocks as ruff intended.

### Completion Notes List

- **All ACs satisfied and verified:** (1) 6 topics @ correct partitions — proven both live and via the testcontainers integration test; (2) idempotent re-run is a no-op — proven live + in test; (3) `EventEnvelope` + `CdrEvent` discriminated-union schema with 16 unit tests; (4) dual trace propagation (`traceparent` header **and** body `trace_id`) — unit-tested with a mocked producer; (5) `key=subscriber_id` bytes — unit-tested; (6) `just provision-topics` recipe wired into `just up` and `just deps` after Redpanda is healthy (`until podman exec redpanda rpk cluster health`).
- **Tests gate:** `uvx --with tox-uv tox` → lint OK (ruff check + ruff format --check + pyrefly 0 errors) and test OK (34 passed, 2 deselected). The 2 deselected `@pytest.mark.slow` integration tests pass when run against rootless Podman: `DOCKER_HOST=unix:///run/user/1000/podman/podman.sock cd cdr-pipeline && uvx --with tox-uv tox -e test -- -m slow`.
- **Task 4 approach (documented per AC #6):** chose the **justfile recipe** path (not a short-lived compose service) because there is no `cdr-pipeline` Dockerfile yet — the consumer image doesn't exist. `provision-topics` mirrors `provision-cognito` (`uvx --with aiokafka,pydantic,pydantic-settings,uuid7 python scripts/provision_topics.py`). The compose-service option is deferred to whenever the cdr-pipeline image lands.
- **Envelope duplication risk (flag for Story 2.8):** per the two-codebase MVP, `service_webapp`'s Story 2.8 simulator producer must emit the **identical** `EventEnvelope` (same 5 fields, UUIDv7 `event_id`, dual-trace rule). The canonical definition lives here in `cdr-pipeline/src/models/envelope.py`; 2.8 should copy it verbatim (or extract a tiny shared module) rather than re-deriving fields. ⚠️ keep the two copies byte-compatible.
- **Dev convenience (user-requested):** added `cdr-pipeline/.env` (gitignored, mirrors `docker/.env`) + `cdr-pipeline/.env.example` (tracked template) so `provision_topics.py`, the future consumer, and local dev runs load `DB__*`/`VALKEY_URL`/`KAFKA_BROKERS` without inline env vars. `pytest-env` (in `pyproject.toml`) remains as the CI belt-and-suspenders for collection without a `.env`.
- **Pre-existing env-var mismatch noted (not fixed here):** `docker/docker-compose.yaml` sets `KAFKA_BOOTSTRAP_SERVERS`/`DATABASE_URL` for the cdr-pipeline container, but `core/config.py` reads `KAFKA_BROKERS`/`DB__*`. The container never runs the consumer yet (no image), so this is latent; Story 2.2/2.x should reconcile the container env to `DB__*`/`KAFKA_BROKERS` when the consumer is containerised.

### File List

- `cdr-pipeline/src/models/__init__.py` — extended (package docstring; was stub from partial dev)
- `cdr-pipeline/src/models/envelope.py` — **fixed** uuid7 import bug; added `cast` + `# noqa: TC003` (was partial dev)
- `cdr-pipeline/src/models/cdr.py` — **NEW**: `CdrEvent` discriminated union (Voice/Sms/Data) mirroring `billing_cdr_events`
- `cdr-pipeline/src/adapters/__init__.py` — **NEW**: adapters package
- `cdr-pipeline/src/adapters/kafka.py` — **NEW**: async `KafkaProducer` (dual trace, `key=subscriber_id` bytes); `MessageBrokerProtocol` impl
- `cdr-pipeline/src/core/protocols/__init__.py` — **NEW**: protocols package
- `cdr-pipeline/src/core/protocols/broker.py` — **NEW**: `MessageBrokerProtocol` (runtime_checkable, async)
- `cdr-pipeline/scripts/provision_topics.py` — **NEW**: idempotent topic provisioning (6 topics, fixed partitions)
- `cdr-pipeline/tests/unit/test_cdr.py` — **NEW**: 16 CDR-schema unit tests
- `cdr-pipeline/tests/unit/test_kafka_producer.py` — **NEW**: 5 producer unit tests (mocked broker)
- `cdr-pipeline/tests/integration/test_provision_topics.py` — **NEW**: 2 `@pytest.mark.slow` testcontainers integration tests
- `cdr-pipeline/pyproject.toml` — **MODIFIED**: runtime deps (pydantic, aiokafka, uuid7) + lint/test tox deps (incl. testcontainers[kafka], pytest-mock)
- `cdr-pipeline/.env` — **NEW** (gitignored): local dev env mirroring `docker/.env`
- `cdr-pipeline/.env.example` — **NEW** (tracked): env template
- `justfile` — **MODIFIED**: added `provision-topics` recipe; wired into `just up` + `just deps` after Redpanda healthy

### Change Log

- 2026-06-22: Story 2.1 implementation complete — CDR envelope model fixed (uuid7 import), CDR payload schema, async producer + broker Protocol, idempotent topic provisioning script, justfile wiring, unit + integration tests. All ACs met; lint + test gates green. Status → review.
