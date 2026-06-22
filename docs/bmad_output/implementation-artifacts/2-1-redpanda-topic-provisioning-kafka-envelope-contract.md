# Story 2.1: Redpanda Topic Provisioning & Kafka Envelope Contract

Status: ready-for-dev

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

- [ ] **Task 1: Define the shared Kafka event envelope model** (AC: #3)
  - [ ] Create `cdr-pipeline/src/models/__init__.py` and `cdr-pipeline/src/models/envelope.py`
  - [ ] `class EventEnvelope(BaseModel)` with fields `event_type: str`, `event_id: UUID`, `trace_id: str`, `timestamp: datetime`, `payload: dict[str, Any]`. Use `model_config = ConfigDict(...)` per pydantic v2; serialise `event_id` as `str`, `timestamp` as ISO-8601 UTC.
  - [ ] Add a factory `EventEnvelope.new(event_type, payload, trace_id, *, event_id=None, timestamp=None)` that defaults `event_id` to a fresh **UUIDv7** (use the `uuid7` package — add `uuid7>=0.1` to deps) and `timestamp` to `datetime.now(UTC)`. Do NOT call `uuid4`.
  - [ ] Add the CDR payload schema `cdr-pipeline/src/models/cdr.py` mirroring `billing_cdr_events` columns (CORE + voice/sms/data variants). Validate `cdr_type ∈ {voice, sms, data}`, `cost_paise: int`, MSISDNs as strings. This is the schema Story 2.2 validates against. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:177-209]
- [ ] **Task 2: Implement the producer helper with dual trace propagation** (AC: #4, #5)
  - [ ] Create `cdr-pipeline/src/adapters/kafka.py` with an aiokafka `AIOKafkaProducer` wrapper (async; `kafka_brokers` from `settings`).
  - [ ] `async publish(topic, *, key, envelope)` serialises the envelope to JSON (UTF-8) as the value, sets `key` to `subscriber_id` bytes, and injects a W3C `traceparent` header built from `envelope.trace_id` into the Kafka message headers. Body already carries `trace_id`.
  - [ ] Expose a `MessageBrokerProtocol` in `cdr-pipeline/src/core/protocols/broker.py` (typed Protocol, async) so the consumer/screener depend on the interface, mirroring the existing `DatabaseProtocol`/`CacheProtocol` DI convention. [Source: architecture.md#1.12.1 (Protocol interfaces, async-only — ARCH-15)]
- [ ] **Task 3: Implement the idempotent provisioning script** (AC: #1, #2, #6)
  - [ ] Create `cdr-pipeline/scripts/provision_topics.py`. Use the aiokafka admin client (`aiokafka.admin.AIOKafkaAdminClient`) — or `kafka-python`'s `KafkaAdminClient` if the aiokafka admin surface is insufficient; prefer aiokafka to avoid a new dep.
  - [ ] Define the topic spec as a module-level list of `(name, partitions, replication_factor=1)`: `cdr.raw`/24, `cdr.enriched.filtered`/24, `cdr.fraud.flagged`/6, `fraud.alerts`/6, `notification.events`/12, `cdr.dlq`/6. (ARCH-10)
  - [ ] List existing topics first; create only the missing ones (`create_topics` with the existing-topic error swallowed). Log `created`/`exists` per topic. Re-running must be a no-op. Connect via `settings.kafka_brokers`.
- [ ] **Task 4: Wire provisioning into compose / justfile** (AC: #1, #6)
  - [ ] Add `provision-topics` recipe to the root `justfile` (pattern: `cd cdr-pipeline && PYTHONPATH=src python scripts/provision_topics.py`), matching the cross-platform `{{ justfile_directory() }}` convention used by `provision-cognito`.
  - [ ] Ensure provisioning runs after Redpanda is healthy on `just up` — either append the recipe call to `up`, or add a short-lived `provision-topics` service to `docker/docker-compose.yaml` (depends_on redpanda: service_healthy, `restart: no`), consistent with how the `flyway` runner is wired. Document the chosen approach in Completion Notes. [Source: 1-2 story (flyway short-lived runner pattern); 1-3 story (justfile recipes)]
- [ ] **Task 5: Tests** (AC: #2, #3, #4)
  - [ ] Unit: `EventEnvelope.new()` produces a UUIDv7 `event_id` (version nibble == 7), UTC timestamp, and round-trips through `model_dump_json()`/`model_validate_json()`.
  - [ ] Unit: the producer helper sets `traceparent` header AND a body `trace_id` equal to the envelope's `trace_id`; key is the `subscriber_id` bytes. Mock the `AIOKafkaProducer` (no live broker).
  - [ ] Integration (`@pytest.mark.slow`/`integration`, testcontainers Redpanda/Kafka): running `provision_topics.py` twice yields the 6 topics with correct partition counts and the second run is a clean no-op. Use `DOCKER_HOST=unix:///run/user/1000/podman/podman.sock` (rootless podman). [Source: 1-4 debug log]

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

### Debug Log References

### Completion Notes List

### File List
