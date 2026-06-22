# Story 2.2: CDR Ingestion Consumer — Dedup & DLQ

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want the CDR pipeline to consume events from `cdr.raw`, deduplicate them idempotently using Valkey, and route failed events to the dead-letter queue,
so that each CDR is processed exactly once and no event is silently lost.

## Acceptance Criteria

1. **Given** a CDR event is published to `cdr.raw`, **When** the aiokafka consumer pool processes it, **Then** the consumer checks `dedup:{cdr_id}` in Valkey with `SET key 1 NX EX 86400` (24h TTL); if the key already existed (NX failed), the event is discarded and a `deduplicated` counter is incremented (FR-57, NFR-9, ARCH-5).
2. **And** if the key did not exist, the event payload is validated against the CDR schema and the (enriched) envelope is forwarded to `cdr.enriched.filtered`, re-propagating `traceparent` header + `trace_id` body.
3. **And** if schema validation fails (or the envelope is malformed), the **raw** event is published to `cdr.dlq` with error metadata (`error_reason`, `original_topic`, `failed_at`, original key/payload) (ARCH-10, FR-57).
4. **And** the consumer pool uses `aiokafka` with `group_id` = `cdr-balance-updater`, async batch processing via `getmany(max_records=500)`; consumer parallelism matches the 24 `cdr.raw` partitions (ARCH-15).
5. **And** the consumer loop lives in `cdr-pipeline/src/consumer/batch_processor.py`; dedup logic in `cdr-pipeline/src/consumer/dedup.py`.
6. **Given** the cdr-pipeline service restarts, **When** it starts up, **Then** it resumes from the **last committed Kafka offset** — offsets are committed only **after** a batch is fully processed, so no committed events are reprocessed and any in-flight (uncommitted) ones are safely re-delivered and absorbed by dedup.

## Tasks / Subtasks

- [ ] **Task 1: Async adapters the consumer depends on** (AC: #1, #4)
  - [ ] `cdr-pipeline/src/adapters/redis.py` — `ValkeyAdapter` implementing `CacheProtocol`, mirroring `service_webapp/src/adapters/redis.py` (`valkey.asyncio.from_url(settings.valkey_url)`). It MUST expose a `set_nx(key, value, ex)` (`SET ... NX EX`) returning bool, plus `incr(key)` for the deduplicated counter. Extend the existing `service_webapp` adapter's method set rather than inventing a different shape. [Source: service_webapp/src/adapters/redis.py:18-53]
  - [ ] `cdr-pipeline/src/adapters/kafka.py` — extend the producer helper from Story 2.1 and add an `AIOKafkaConsumer` factory bound to `settings.kafka_brokers` + `group_id="cdr-balance-updater"`, `enable_auto_commit=False` (manual commit), `auto_offset_reset="earliest"`.
  - [ ] Define `CacheProtocol`/`MessageBrokerProtocol` methods used here in `cdr-pipeline/src/core/protocols/`. Consumer code depends on protocols, not concrete adapters (DI convention). [Source: architecture.md#1.12.1 (ARCH-15, typed Protocols)]
- [ ] **Task 2: Dedup module** (AC: #1, NFR-9)
  - [ ] `cdr-pipeline/src/consumer/dedup.py` — `async is_duplicate(cache, cdr_id) -> bool`: performs `SET dedup:{cdr_id} 1 NX EX 86400`; returns `True` when the key already existed (NX failed → duplicate), `False` when freshly set (first sight). Key domain exactly `dedup:{cdr_id}`, 24h TTL (ARCH-5).
  - [ ] On duplicate, increment an in-process `deduplicated` counter (and log at debug with `cdr_id` only — never MSISDN/PII). Expose the counter so Story 2.5/observability can read it.
- [ ] **Task 3: DLQ handler** (AC: #3)
  - [ ] `cdr-pipeline/src/dlq/handler.py` — `async to_dlq(producer, *, raw_value, raw_key, error_reason, original_topic)`: publishes the **original raw bytes** plus error metadata to `cdr.dlq` keyed by `cdr_id` (or the original key when `cdr_id` is unparseable). Metadata shape must match what Story 2.5's `GET /api/v1/admin/dlq` returns: `cdr_id`, `error_reason`, `original_topic`, `failed_at` (UTC ISO-8601), and the raw payload. Wrap the DLQ record itself in an `EventEnvelope` (event_type `cdr.dlq`) so trace continuity is preserved.
- [ ] **Task 4: Batch consumer loop** (AC: #2, #4, #6)
  - [ ] `cdr-pipeline/src/consumer/batch_processor.py` — async loop: `getmany(max_records=500, timeout_ms=...)` → for each record: parse `EventEnvelope`; extract `trace_id` and continue the OTEL trace via `opentelemetry.propagate.extract(headers)`; dedup check; on first-sight validate the CDR payload (`models/cdr.py`); on success forward enriched envelope to `cdr.enriched.filtered`; on validation/parse failure route raw to `cdr.dlq`. **Commit offsets only after the whole batch is handled** (`await consumer.commit()`), giving at-least-once + idempotent dedup. (AC #6)
  - [ ] `cdr-pipeline/src/main.py` — replace the stub: build adapters, run `load_balances_from_postgres()` is **out of scope here** (Story 2.3); start the consumer pool and await it. Graceful shutdown stops the consumer and flushes the producer.
  - [ ] Parallelism: a single `AIOKafkaConsumer` in a `cdr-balance-updater` group with 24 partitions can be scaled by running multiple consumer tasks/instances; for MVP single-process, document the chosen task count and that Kafka rebalancing assigns partitions. Do not exceed 24 active consumers. [Source: architecture.md#1.4.1 (batch=500, commit after batch); decision log §1.2.4 (getmany)]
- [ ] **Task 5: Tests** (AC: #1, #2, #3, #6)
  - [ ] Unit: `dedup.is_duplicate` returns `False` on first key, `True` on second (mock cache `set_nx` returning True then False); TTL/flags asserted (`NX`, `EX=86400`).
  - [ ] Unit: a malformed/invalid CDR payload routes to DLQ with correct metadata (mock producer; assert topic `cdr.dlq`, `error_reason`, raw bytes preserved); a valid one forwards to `cdr.enriched.filtered` with `traceparent` header + body `trace_id` carried through.
  - [ ] Unit: batch processing commits offsets **once after** the batch (assert `commit()` called after all records processed, not per-record).
  - [ ] Integration (`@pytest.mark.slow`, testcontainers Redpanda + Valkey): publish a duplicate pair to `cdr.raw`; assert exactly one forwarded to `cdr.enriched.filtered` and the duplicate counted; restart consumer and confirm no committed re-processing. Rootless podman socket. [Source: 1-4 debug log]

## Dev Notes

### Scope boundary

- **DOES:** consume `cdr.raw`, Valkey `SET NX` dedup (`dedup:{cdr_id}`, 24h), CDR schema validation, forward valid events to `cdr.enriched.filtered`, route failures to `cdr.dlq` with metadata, manual offset commit after batch, the consumer entrypoint. Unit + one integration test.
- **DOES NOT:** deduct balance / write to Valkey `balance:{msisdn}` or flush to Postgres (Story 2.3 — `consumer/balance_writer.py`), write audit rows (2.4), run the fraud pre-screener (`screener/`, Epic 6), or expose admin/DLQ endpoints (2.5). Enrichment here = envelope pass-through + validation; real fraud/notification enrichment is downstream. Keep the consumer lean and on the hot path only for dedup + forward.

### Hard dependency on Story 2.1

- This story assumes Story 2.1 has landed: the 6 topics exist (provisioned), `EventEnvelope` + CDR payload schema exist in `cdr-pipeline/src/models/`, and the producer helper guarantees `traceparent` header + `trace_id` body. Reuse them; do not redefine the envelope. If 2.1 is not yet merged, that is a blocker — flag it. [Source: this epic, Story 2.1]

### Dedup is the correctness core (NFR-9, ARCH-5)

- Exactly-once **deduction** is achieved by exactly-once **processing**, which is achieved by the Valkey dedup guard, NOT by Kafka (Kafka is at-least-once). `dedup:{cdr_id}` SET with `NX EX 86400`: the atomic NX is the dedup decision — if the SET succeeds the event is new; if it fails the `cdr_id` was seen within 24h and the event is dropped. This is shared across all consumers (Valkey is the single source). [Source: architecture.md#1.7.3 (ARCH-5 key domains, dedup:{cdr_id} 24h); decision log §1.2.5 (Valkey SET vs alternatives); epics.md#Story-2.2 (line 890)]
- `cdr_id` is the CDR's UUIDv7 (the `id`/`cdr_id` in the payload), NOT the envelope `event_id`. Dedup on `cdr_id`. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:178; epics.md#Story-2.2]
- **There is no `cdr_dedup` Postgres table.** Dedup state lives only in Valkey (24h TTL). Ignore any epic text implying a Postgres dedup table. [Source: architecture.md#1.7.3]

### Offset / delivery semantics (AC #6)

- `enable_auto_commit=False`; commit after each fully-processed batch. A crash mid-batch leaves the offset uncommitted → those records are re-delivered on restart → dedup absorbs the ones already applied. Net effect: at-least-once delivery + idempotent processing = effectively exactly-once. [Source: architecture.md#1.4.3 (commit after batch success, lines 193-196)]

### Trace propagation (NFR-17)

- Continue the trace: extract context from the incoming Kafka headers (`opentelemetry.propagate.extract`), and when forwarding to `cdr.enriched.filtered` or `cdr.dlq` set `traceparent` header + `trace_id` body via the Story 2.1 producer helper. The same `trace_id` must survive raw → enriched → (later) fraud/notification + the audit row (Story 2.4). [Source: architecture.md#1.11.4 (line 863); NFR-17; epics.md#Story-2.4]

### Valkey adapter — reuse the established shape

- `service_webapp/src/adapters/redis.py` `ValkeyAdapter` already wraps `valkey.asyncio.from_url(url)` with `set_str/get_str/delete/ping/close`. Mirror it in `cdr-pipeline/src/adapters/redis.py` and ADD the methods this story needs (`set_nx`, `incr`). Keep the constructor `__init__(self, url: str)` and `CacheProtocol` contract consistent across both codebases. Valkey runs with `maxmemory-policy noeviction` (Story 1.2). [Source: service_webapp/src/adapters/redis.py:18-53; 1-2 story (valkey config)]

### Config & deps

- `settings.kafka_brokers`, `settings.valkey_url`, `settings.kafka_consumer_group` are present (`cdr-pipeline/src/core/config.py`). Note the AC mandates `group_id="cdr-balance-updater"`, which differs from the config default `"cdr-pipeline"` — pass the explicit group id (or update the default; document the choice). Add `aiokafka>=0.11`, `valkey[asyncio]>=6`, `opentelemetry-sdk>=1.25` and `uuid7>=0.1` to `cdr-pipeline/pyproject.toml` runtime deps AND the relevant tox env `deps` (this codebase pins per-env). [Source: cdr-pipeline/src/core/config.py:42-46; cdr-pipeline/pyproject.toml:277-296]

### PII hygiene

- Never log raw MSISDN/from_number/to_number/IMEI. Log `cdr_id`, `subscriber_id` (UUID), counts. If a phone number must appear, mask to last 4 (`[-4:]`). DLQ raw payloads may contain PII — that is acceptable inside Kafka but DLQ inspection responses (Story 2.5) must mask. [Source: architecture.md#1.11.6 (PII hygiene); 1-6 story (mask_msisdn)]

### Testing standards summary

- `uv tox` `lint`/`test`; unit tests mock the broker + cache (fast, default); one `slow` testcontainers integration test (Redpanda + Valkey) under rootless podman. Add new runtime imports to tox env `deps`. ruff 120 / py311 / numpy docstrings. [Source: cdr-pipeline/pyproject.toml; 1-4 story]

### Project Structure Notes

- **NEW:** `cdr-pipeline/src/consumer/{__init__,batch_processor,dedup}.py`, `cdr-pipeline/src/dlq/{__init__,handler}.py`, `cdr-pipeline/src/adapters/{redis,kafka}.py` (kafka extended from 2.1), `cdr-pipeline/src/core/protocols/{cache,broker}.py`, tests.
- **MODIFIES:** `cdr-pipeline/src/main.py` (stub → consumer entrypoint), `cdr-pipeline/pyproject.toml` (deps).
- **Path note:** use `src/consumer/` (architecture §1.12.1), NOT `src/pipeline/` as the epic AC text says. [Source: architecture.md#1.12.1]
- The `balance_writer.py` file in the same `consumer/` package is **Story 2.3's** deliverable — leave a clear seam (the batch processor should call a balance hook that 2.3 implements), but do not implement deduction here.

### References

- [Source: epics.md#Story-2.2 (lines 876-905)]
- [Source: architecture.md#1.4.1 (consumer pool, batch=500), #1.4.3 (commit-after-batch, lines 193-196)]
- [Source: architecture.md#1.7.3 (ARCH-5: dedup:{cdr_id} 24h, Valkey-only)]
- [Source: architecture.md#1.7.6 (ARCH-10: cdr.raw 24p, cdr.dlq 6p), #1.11.4 (envelope + traceparent)]
- [Source: architecture.md#1.12.1 (cdr-pipeline source tree, ARCH-15)]
- [Source: architecture.md#1.11.6 (PII hygiene)]
- [Source: service_webapp/src/adapters/redis.py:18-53 (ValkeyAdapter shape)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:177-209 (billing_cdr_events / cdr_id)]
- [Source: cdr-pipeline/src/core/config.py, cdr-pipeline/pyproject.toml]
- [Source: 1-2 story (redpanda/valkey compose), 1-4 story (OTEL extract, testcontainers), 1-6 story (PII masking)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
