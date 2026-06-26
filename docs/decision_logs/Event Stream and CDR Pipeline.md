# 1. CDR Streaming Pipeline — Final Architecture & Decision Log

---

## 1.1. Final Architecture

### 1.1.1. Data Flow

```
CDR Source (10K rec/sec)
  │
  ▼
Kafka: cdr.raw  [24 partitions, key = subscriber_id]
  │
  ▼
Consumer Worker Pool  [aiokafka, group_id='cdr-balance-updater']
  │  batch=500 | commit offset AFTER batch success
  │
  ├─► Dedup ──► Valkey SET (cdr_record_id, TTL=24h)
  │
  ├─► Balance Update ──► Valkey INCRBY pipeline (atomic)
  │                         └─► Async flush → PostgreSQL (bulk upsert, every 2s or 5K records)
  │
  └─► Filter Logic ──► Kafka: cdr.enriched.filtered
                          ├─► Downstream A  (Kafka consumer, any language)
                          ├─► Downstream B  (REST webhook via adapter)
                          └─► Downstream N  ...
```

### 1.1.2. Component Summary

| Component | Technology | Role |
|---|---|---|
| Event Bus | Apache Kafka (24 partitions) | Primary ingest, fan-out, replay |
| Consumer | aiokafka, consumer group | Parallel batch processing, offset management |
| Dedup Store | Valkey SET | Idempotency on `cdr_record_id` |
| Balance Write Buffer | Valkey INCRBY | Atomic fast writes, absorbs 10K/sec |
| Balance Source of Truth | PostgreSQL | Bulk upsert, audit, reporting |
| Filtered Fan-out | Kafka topic `cdr.enriched.filtered` | Downstream pipeline isolation |
| Downstream Interop | Kafka consumers OR REST adapter | Polyglot consumer support |
| Dead Letter Queue | Kafka DLQ topic | Poison record isolation, manual replay |
| FastAPI | Management plane only | Pause/resume workers, DLQ inspection, metrics |

### 1.1.3. Key Design Principles

- **Partition count = 24** — Supports 24 parallel workers. 2.4x headroom over minimum at peak. Set once at topic creation.
- **At-least-once + idempotency** — Offset committed only after full batch success. Worker crash = uncommitted offset = re-delivery. Valkey SET deduplicates re-delivered records.
- **Valkey as write buffer** — Absorbs 10K/sec via INCRBY pipeline. No Postgres row-level lock contention on hot path. AOF + replica for durability.
- **Async Postgres flush** — Bulk upsert every 2 seconds or 5,000 records. Postgres is audit and reporting layer, not the write hot path.
- **FastAPI = management plane only** — HTTP endpoints for DLQ inspection, worker control, metrics. Not in the record processing critical path.

---

## 1.2. Decision Log

### 1.2.1. Event Bus — Kafka

**Decision:** Kafka over SQS, Pulsar, RabbitMQ

| Option               | Tradeoff                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Kafka** *(chosen)* | High throughput, native consumer groups, replay on failure, fan-out without message duplication                          |
| SQS                  | Zero ops — but max 10 msg/batch, no replay after ack, fan-out requires SNS+queue sprawl, 100+ pollers needed for 10K/sec |
| Pulsar               | Strong multi-tenancy and geo-replication — heavier ops, smaller Python ecosystem, overkill for single-region             |
| RabbitMQ             | Good for task queues — poor for stream replay and fan-out at this volume                                                 |

---

### 1.2.2. Consumer Framework — Aiokafka

**Decision:** aiokafka over Celery, Faust

| Option | Tradeoff |
|---|---|
| **aiokafka** *(chosen)* | Native async Kafka consumer, `getmany()` for true micro-batching, direct offset control, minimal overhead |
| Celery | Built for task queues not streams — awkward batching, adds broker layer on top of Kafka, no offset semantics |
| Faust | Python-native stream processing with local state — less actively maintained, more opinionated, adds complexity |

---

### 1.2.3. Balance Store — Valkey + PostgreSQL

**Decision:** Valkey write buffer + PostgreSQL source of truth over DynamoDB or Postgres-only

| Option | Tradeoff |
|---|---|
| **Valkey + Postgres** *(chosen)* | Valkey absorbs 10K/sec atomically (INCRBY), no row contention; Postgres for audit, reporting, SQL. Decouples write throughput from persistence. |
| DynamoDB | Atomic ADD, managed, consistent latency — expensive at sustained 10K writes/sec, no ad-hoc SQL, AWS lock-in |
| Postgres only | Full SQL, relational — 10K/sec direct writes cause hotspot row contention on balance rows without sharding |
| Valkey only | Fast — no persistent audit trail, no SQL reporting, recovery risk without careful AOF + replica config |

---

### 1.2.4. Batch Processing — getmany()

**Decision:** Micro-batch via `getmany(max_records=500)` over record-at-a-time or Celery batch tasks

| Option | Tradeoff |
|---|---|
| **getmany(max_records=500)** *(chosen)* | 500 records/call with Valkey pipeline — 20 batches/sec at 10K/sec peak. ~50x fewer network round-trips vs record-at-a-time. |
| Record-at-a-time | Simple — 10K individual Valkey + DB calls/sec unsustainable. High latency tail under load. |
| Celery batch tasks | Max 10 msg/call equivalent, no Kafka offset semantics, visibility timeout risk on slow batches |

---

### 1.2.5. Idempotency — Valkey SET on cdr_record_id

**Decision:** Valkey SET with TTL over DB unique constraint or in-memory application check

| Option | Tradeoff |
|---|---|
| **Valkey SET + 24h TTL** *(chosen)* | Sub-millisecond check, shared across all workers, TTL auto-expires old IDs, no DB round-trip on hot path |
| Postgres unique constraint | Reliable — adds a DB write on every record for dedup only. Doubles DB load on hot path. |
| In-memory per-worker | Fast — not shared across workers. Fails on multi-worker deployment. Re-delivered records not deduplicated across restarts. |

---

### 1.2.6. Fan-out — Kafka Filtered Topic

**Decision:** Dedicated Kafka topic `cdr.enriched.filtered` over REST push, SNS, or DB polling

| Option                              | Tradeoff                                                                                                                                 |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Kafka filtered topic** *(chosen)* | Zero coupling, polyglot consumers maintain own offset, no message duplication, replay available. Adding consumer = zero producer change. |
| REST push from worker               | Worker owns downstream reliability — adds retry, timeout, circuit breaker complexity to the processing hot path                          |
| SNS + SQS                           | Each downstream needs own queue, message stored N times, adding consumer requires infra change                                           |
| Shared DB polling                   | High DB load, latency, no push semantics, polling interval creates artificial lag                                                        |

---

### 1.2.7. FastAPI Role — Management Plane Only

**Decision:** FastAPI as ops layer only, not as ingest endpoint

| Option | Tradeoff |
|---|---|
| **Management plane** *(chosen)* | Handles DLQ inspection, worker control, metrics APIs. Not in record hot path. Clean separation of concerns. |
| FastAPI as ingest endpoint | HTTP overhead per record, connection limits, no native replay or offset semantics. Wrong tool for 10K/sec stream ingest. |

---

*Stack: Kafka + aiokafka + Valkey + PostgreSQL*