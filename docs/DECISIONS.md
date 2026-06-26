# 1. Target State

![Decisions Target](bmad_output/planning-artifacts/architecture.md#132-decided-stack--target-state)

# 2. MVP State

![Decisions MVP](bmad_output/planning-artifacts/architecture.md#131-decided-stack--mvp)

# 3. Decision Log (Target State)

This log records the technology decision for each architectural component of the **target state** (production on AWS, `ap-south-1`), the alternatives that were considered, and the tradeoff that settled each choice. Every entry follows the same structure: the chosen option is bolded, the rejected alternatives are listed with the reason they lost.

> **Recurring drivers.** The same forces shape most decisions below; they are named here once and referenced rather than re-explained in every cell:
>
> - **Throughput** — 100K events/sec CDR ingest (target), served by a 24-partition event bus.
> - **P95 latency** — balance deduction ≤ 200ms; every agent/LLM path is strictly off the hot path.
> - **Data residency** — India only (TRAI); all target infrastructure lives in AWS `ap-south-1`, no cross-region transfer.
> - **Idempotency** — exactly-once deduction (Valkey SET, 24h TTL) layered on at-least-once delivery.
> - **Compliance** — TRAI 6-year audit retention; PCI-DSS card tokenisation; AES-256 PII at rest.
> - **Event-driven fan-out** — CDR ingestion fans out to balance, fraud-screening, notification, and segmentation in parallel; polyglot consumers.
> - **Managed over self-managed** where ops cost exceeds the control benefit; self-managed (EKS, Milvus, Keycloak, LangFuse) only where scale or feature demands it.

Decisions are grouped by architectural domain. Where the MVP differs materially it is noted inline (`MVP:`); the primary rationale is always the target state.

---

## 3.1. A. Event Streaming & CDR Pipeline

### 3.1.1. A.1 Event Bus — Amazon MSK (Apache Kafka)

**Decision:** Amazon MSK (managed Kafka) over self-managed Kafka/Redpanda, Amazon Kinesis, SQS+SNS, Pulsar

| Option                               | Tradeoff                                                                                                                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Amazon MSK** *(chosen)*            | Managed brokers/partitions, native consumer groups, replay on failure, fan-out without message duplication. Drives throughput + fan-out + multi-consumer replay simultaneously. 24-partition topics, Mumbai. |
| Self-managed Kafka / Redpanda on EKS | Same Kafka semantics, full control — operator owns broker patching, rebalancing, durability tuning. Ops cost not justified once MSK is available. *(MVP uses Redpanda on Podman.)*                           |
| Amazon Kinesis Data Streams          | Managed, sharded — not Kafka-wire-compatible (limits consumer ecosystem), 1MB/shard limits and per-shard cost make 100K eps expensive, weaker replay ergonomics.                                             |
| SQS (+ SNS for fan-out)              | Zero ops — but 10 msg/batch, no replay after ack, fan-out requires SNS + per-consumer queue sprawl, and 100+ pollers needed for 100K eps.                                                                    |
| Pulsar                               | Strong multi-tenancy and geo-replication — heavier ops, smaller Python/Rust ecosystem, overkill for single-region.                                                                                           |

---

### 3.1.2. A.2 CDR Pipeline Runtime — Rust (tokio + rdkafka)

**Decision:** Rust (tokio + rdkafka) over Python aiokafka, Go, Java/Scala

| Option                       | Tradeoff                                                                                                                                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Rust** *(chosen)*          | Zero-GC, deterministic sub-200ms P95, maximal consumer throughput at 100K eps. Pays back only on the one path where throughput/latency is a hard NFR.                                          |
| Python aiokafka              | MVP choice and proven at 10K eps — but the GIL and GC pauses cap headroom well below 100K eps sustained. Kept as the MVP runtime; not the target hot path. *(See A.3 for the batching model.)* |
| Go (sarama / franz-go)       | Strong concurrency and throughput — adds a second non-Python language to the stack for a single service; Rust chosen for the zero-GC latency tail.                                             |
| Java / Scala (Kafka Streams) | Mature streaming ecosystem — JVM footprint and a third language/runtime; no streaming-framework features needed beyond consumer + offset control.                                              |

---

### 3.1.3. A.3 Micro-batch Processing — Consumer Batch of 500

**Decision:** micro-batch via `getmany(batch=500)` over record-at-a-time or task-queue batches

| Option                            | Tradeoff                                                                                                                                                                                        |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **getmany(batch=500)** *(chosen)* | 500 records/call fanned into a single Valkey pipeline — ~20 batches/sec at 100K eps peak, ~50x fewer network round-trips than record-at-a-time. Offset committed only after full batch success. |
| Record-at-a-time                  | Simplest correctness model — 100K individual Valkey + DB calls/sec is unsustainable; high latency tail under load.                                                                              |
| Celery / task-queue batches       | Adds a broker layer on top of Kafka, no native offset semantics, visibility-timeout risk on slow batches.                                                                                       |

---

### 3.1.4. A.4 Idempotency — Valkey SET on cdr_record_id

**Decision:** Valkey SET + 24h TTL over a DB unique constraint, in-memory check, or probabilistic filter

| Option                              | Tradeoff                                                                                                                                                                                                                           |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Valkey SET + 24h TTL** *(chosen)* | Sub-millisecond check shared across all workers, auto-expires old IDs, no DB round-trip on the hot path. Sizing: 100K unique IDs/sec × 86,400s TTL × ~60 bytes/key ≈ 500GB RAM at steady-state — capacity-planned, not accidental. |
| Postgres unique constraint          | Reliable — adds a DB write on every record purely for dedup, doubling DB load on the hot path.                                                                                                                                     |
| In-memory per-worker                | Fast — not shared across workers; re-delivered records are not deduplicated across restarts or worker boundaries.                                                                                                                  |
| RedisBloom (Cuckoo filter)          | ~1000x memory reduction — trades deterministic exactness for probabilistic drops; only acceptable if occasional false-positive drops are tolerable (they are not for billing).                                                     |

---

### 3.1.5. A.5 Fan-out — Kafka Filtered Topic

**Decision:** dedicated topic `cdr.enriched.filtered` over REST push, SNS+SQS, or DB polling

| Option                              | Tradeoff                                                                                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Kafka filtered topic** *(chosen)* | Zero producer↔consumer coupling, polyglot consumers maintain their own offsets, no message duplication, replay available. Adding a consumer = zero producer change. |
| REST push from worker               | Worker owns downstream reliability — pushes retry/timeout/circuit-breaker complexity onto the processing hot path.                                                  |
| SNS + SQS                           | Each downstream needs its own queue, the message is stored N times, adding a consumer requires an infra change.                                                     |
| Shared DB polling                   | High DB load, latency, no push semantics; the polling interval creates artificial lag.                                                                              |

---

### 3.1.6. A.6 Dead-Letter Handling — DLQ Topic + Manual Replay

**Decision:** `cdr.dlq` Kafka topic + DLQ inspector API over silent drop or per-consumer retry queues

| Option                               | Tradeoff                                                                                                                                              |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **DLQ topic + inspector** *(chosen)* | Poison records isolated without blocking the partition; manual replay via a management API. Keeps the hot path moving while failures are recoverable. |
| Silent skip / log-only               | Simplest — loses records silently; unacceptable for billing-grade data.                                                                               |
| Per-consumer retry queues            | More retry nuance — multiplies topic/queue count and offset bookkeeping; replay semantics no better than a single DLQ for this topology.              |

---

### 3.1.7. A.7 CDR Simulator — Rust Binary (Shared, Feature-flagged)

**Decision:** same Rust codebase as the pipeline, feature-flagged, over a separate generator or a generic load tool

| Option                                   | Tradeoff                                                                                                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Rust binary (shared code)** *(chosen)* | Reuses the pipeline's serialization/schema code so generated events are wire-identical; hits target throughput for load testing without a second schema to keep in sync. |
| Separate Python generator                | MVP approach (capped at 100 CDRs/shot) — cannot reach 100K eps and risks schema drift from the real producer.                                                            |
| Generic load tool (k6 / perf)            | High raw throughput — emits synthetic shapes, not the real CDR schema, so it tests bandwidth rather than the pipeline correctness path.                                  |

---

## 3.2. B. Data Layer

### 3.2.1. B.1 Balance / Hot-Write Path — ElastiCache Valkey Buffer + Async Flush to RDS

**Decision:** ElastiCache Valkey write buffer (INCRBY) + async bulk upsert → RDS over Postgres-only, DynamoDB, Valkey-only, or Cassandra/RocksDB

| Option                           | Tradeoff                                                                                                                                                                                                                                                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Valkey + Postgres** *(chosen)* | Valkey absorbs the write spike atomically (INCRBY), no row contention; Postgres stays the source of truth for audit, reporting, SQL. Decouples write throughput from persistence. Balance keys have **no TTL** (running counter), `maxmemory-policy noeviction` enforced, Postgres warm-loaded on startup. |
| DynamoDB                         | Atomic ADD, managed, consistent latency — expensive at sustained high writes/sec, no ad-hoc SQL, AWS lock-in.                                                                                                                                                                                              |
| Postgres only                    | Full SQL/relational — direct high-frequency writes cause hotspot row contention on balance rows without sharding.                                                                                                                                                                                          |
| Valkey only                      | Fast — no persistent audit trail, no SQL reporting, recovery risk without careful AOF + replica config.                                                                                                                                                                                                    |
| Cassandra / RocksDB              | LSM-tree, append-only, no update contention — heavyweight, eventual consistency (hard to tune, latency-affected), poor fit for a highly relational normalized model that relies on JOINs.                                                                                                                  |

---

### 3.2.2. B.2 Primary Database — Amazon RDS PostgreSQL (Multi-AZ)

**Decision:** RDS PostgreSQL Multi-AZ over Aurora Postgres, self-managed EC2 Postgres, DynamoDB, or distributed SQL

| Option                                 | Tradeoff                                                                                                                                                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **RDS Postgres (Multi-AZ)** *(chosen)* | Managed HA + automated failover, read replicas for reporting, full SQL/relational fit, pgcrypto/pg_partman/pg_trgm extensions, Mumbai. Predictable, well-understood ops.                                      |
| Aurora Postgres                        | Higher write throughput and faster failover — proprietary storage engine, premium pricing, some extension/feature lag vs community Postgres; not needed at this write profile (writes are buffered, see B.1). |
| Self-managed Postgres on EC2           | Full control — operator owns patching, backups, failover, upgrades; unjustified ops burden.                                                                                                                   |
| DynamoDB                               | Managed scale — no relational SQL/JOINs, no ad-hoc reporting, vendor lock-in; wrong model for the normalized billing/identity schema.                                                                         |
| CockroachDB / distributed SQL          | Global scale and multi-active writes — significant cost and complexity for a single-region, residency-bound workload.                                                                                         |

---

### 3.2.3. B.3 Vector Store — Milvus Distributed (Self-managed on EKS)

**Decision:** Milvus Distributed over pgvector, Pinecone, OpenSearch k-NN, or Weaviate

| Option                            | Tradeoff                                                                                                                                                                                                                    |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Milvus Distributed** *(chosen)* | Fixed for both MVP and target. Horizontally scaled query/data nodes for production RAG throughput; same `pymilvus` client and collection schema as MVP — migration is a `uri` change only. Hybrid BM25 + HNSW + RRF rerank. |
| pgvector                          | No new component — caps out on vector-only scale and lacks first-class hybrid/RRF; acceptable only at small corpus size.                                                                                                    |
| Pinecone                          | Fully managed — SaaS data egress conflicts with India residency, per-dimension pricing, weaker self-hosted story.                                                                                                           |
| OpenSearch k-NN                   | Bundles search + vectors — heavier than a dedicated vector engine, k-NN recall/throughput below purpose-built Milvus at this scale.                                                                                         |
| Weaviate                          | Capable hybrid search — smaller ecosystem, another operator surface; no advantage over Milvus given the fixed decision.                                                                                                     |

---

### 3.2.4. B.4 Kafka Topic Topology — Per-Traffic-Class Partitions, Subscriber-Keyed

**Decision:** fixed partition counts per traffic class, key = `subscriber_id` / `msisdn`, over a single high partition count or dynamic partitioning

| Option                                       | Tradeoff                                                                                                                                                                                                                                             |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Per-class partitions + keying** *(chosen)* | 24 partitions for high-volume CDR topics (`cdr.raw`, `cdr.enriched.filtered`), 6–12 for lower-volume (`cdr.fraud.flagged`, `fraud.alerts`, `notification.events`, `cdr.dlq`). Subscriber keying gives per-subscriber ordering. Set once at creation. |
| Single very-high partition count             | Maximises parallelism everywhere — over-provisions low-volume topics, wastes broker resources, complicates consumer scaling.                                                                                                                         |
| Dynamic / auto-partitioning                  | Elastic — no native Kafka support; repartitioning breaks ordering and offsets.                                                                                                                                                                       |

---

### 3.2.5. B.5 Audit Archive — S3 + Glacier, 6-Year Lifecycle

**Decision:** immutable Postgres audit (INSERT-only role) → pg_partman → S3 lifecycle (Standard → IA @2yr → Glacier @6yr) over pure-Postgres retention or DynamoDB

| Option                                         | Tradeoff                                                                                                                                                                                 |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Postgres → S3/Glacier lifecycle** *(chosen)* | Recent audit stays queryable in Postgres (INSERT-only app role, no UPDATE/DELETE grants); pg_partman ages rows to S3; lifecycle policy meets TRAI 6-year retention at storage-tier cost. |
| Postgres-only retention                        | Full SQL queryability — 6 years of append-only audit bloats the OLTP database and backup windows.                                                                                        |
| DynamoDB                                       | Managed scale — no SQL audit querying, TTL ≠ regulatory retention, harder to prove immutability.                                                                                         |
| Glacier Vault (direct, no S3 tier)             | Cheapest cold storage — loses the warm/recent tier needed for operational audit queries.                                                                                                 |

---

### 3.2.6. B.6 Schema Conventions — Single `public` Schema, Domain-Prefixed Tables

**Decision:** `{domain}_{table}` names in one `public` schema over multi-schema (`identity.*`, `billing.*`) or schema-per-service

| Option                                      | Tradeoff                                                                                                                                                                                                  |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Domain prefix, single schema** *(chosen)* | Avoids cross-schema permission overhead at this scale; domain is encoded in the table name (`billing_wallet_balances`, `fraud_cases`, `support_tickets`). Prefix makes a future schema split unambiguous. |
| Separate PostgreSQL schemas                 | Cleaner namespace isolation — adds permission-management overhead without meaningful benefit at current scale; migration path retained.                                                                   |
| Schema-per-service                          | Strong service ownership — fragments relational integrity across the billing/identity core that benefits from JOINs.                                                                                      |

---

## 3.3. C. Application & Service Plane

### 3.3.1. C.1 Service Decomposition — Microservices

**Decision:** domain microservices (~11–18 services) over the MVP two-codebase split, a single monolith, or function-per-endpoint

| Option                         | Tradeoff                                                                                                                                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Microservices** *(chosen)*   | Independent deployment and per-service scaling (Rust only on the CDR hot path; Python FastAPI everywhere else). Aligns with EKS, ~18 services/agents, and the polyglot fan-out topology. |
| MVP two-codebase structure     | Proven for PoC (`cdr-pipeline` + `service_webapp`, no inter-service HTTP) — does not decompose enough to scale the agent/service plane independently at target load.                     |
| Single monolith                | Simplest ops — couples the 100K eps CDR path to the Python service plane and blocks independent scaling/language choice.                                                                 |
| Lambda / function-per-endpoint | Elastic — no long-lived consumers (breaks the Kafka consumer model), cold-start latency, awkward for stateful agents.                                                                    |

---

### 3.3.2. C.2 Application Backend — Python 3.14 + FastAPI

**Decision:** Python FastAPI for all domain services over Node/NestJS, Go, or Java/Spring

| Option                          | Tradeoff                                                                                                                                                                                             |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Python + FastAPI** *(chosen)* | One language for the service + agent plane; native fit for LangGraph, pymilvus, WeasyPrint (PDF receipts). Async, typed, fast to iterate; throughput handled by the buffer (B.1), not the framework. |
| Node + NestJS                   | Strong async I/O — loses the Python LangChain/LangGraph + pymilvus ecosystem that the agent plane depends on.                                                                                        |
| Go                              | Excellent throughput — no first-class LangGraph/agent ecosystem; would force the agent plane onto a second runtime.                                                                                  |
| Java + Spring Boot              | Mature enterprise stack — JVM footprint and verbose model for a Python-centric team; no advantage over FastAPI at this profile.                                                                      |

---

### 3.3.3. C.3 API Gateway — AWS API Gateway + ALB

**Decision:** API Gateway (JWT authorizer + per-subscriber usage plans) backed by ALB (TLS) over app-layer middleware, Kong, or Nginx-only

| Option                           | Tradeoff                                                                                                                                                                                           |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **API Gateway + ALB** *(chosen)* | Native per-role/per-subscriber rate limiting (FR-36), JWT validation, and blacklist enforcement at the edge (429 rate-limited / 403 blacklisted). TLS 1.2+ terminated at ALB; backend stays clean. |
| App-layer rate-limit middleware  | Flexible — costs a hop and competes for request-handling capacity; blacklist checks leak into every service.                                                                                       |
| Kong / self-managed gateway      | Feature-rich — another self-managed control plane to operate; API Gateway is managed and sufficient.                                                                                               |
| Nginx Ingress only               | Routing + TLS — no first-class JWT usage-plan/rate-limit model; would need Lua/plugins to reach feature parity.                                                                                    |

---

### 3.3.4. C.4 Management / Ops Plane — FastAPI Off the Hot Path

**Decision:** FastAPI as the ops/control plane only (DLQ inspection, worker pause/resume, metrics) over FastAPI as an ingest endpoint

| Option                          | Tradeoff                                                                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Management plane** *(chosen)* | Handles DLQ inspection, worker control, and metrics APIs across services. Never in the record hot path. Clean separation of control from data. |
| FastAPI as ingest endpoint      | HTTP overhead per record, connection limits, no native replay or offset semantics — the wrong tool for high-rate stream ingest.                |

---

### 3.3.5. C.5 DB Client — Psycopg3 (Async, SQL-Only, No ORM)

**Decision:** psycopg3 (async, binary) + raw SQL over SQLAlchemy ORM, asyncpg, or Django ORM

| Option                  | Tradeoff                                                                                                                                                  |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **psycopg3** *(chosen)* | Native async protocol, binary mode, fast; SQL-only keeps the query in the code (CQRS `queries.py` / `commands.py`), no ORM/DBL mismatch or N+1 surprises. |
| SQLAlchemy ORM          | Productive mapping — hides SQL, risks N+1, adds an abstraction layer over a schema already owned by Flyway migrations.                                    |
| asyncpg                 | Fast — separate protocol implementation; psycopg3 chosen for broader feature set and binary mode.                                                         |
| Django ORM              | Tied to Django — framework we are not using; query-builder/ORM explicitly excluded by the SQL-only rule.                                                  |

---

### 3.3.6. C.6 DB Migrations — Flyway (SQL-Native)

**Decision:** Flyway versioned SQL migrations over Alembic, Liquibase, or ORM-generated DDL

| Option                | Tradeoff                                                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Flyway** *(chosen)* | All schema evolution (tables, indexes, views, materialized views, triggers, grants) as versioned SQL; no ORM-generated DDL; reproducible, reviewable. *(Alembic was removed.)* |
| Alembic               | Python-native — couples migrations to SQLAlchemy autogenerate; removed in favour of SQL-native control.                                                                        |
| Liquibase             | Capable — YAML/XML abstraction adds a layer over plain SQL without benefit for a SQL-fluent team.                                                                              |
| ORM-generated DDL     | Convenient — drifts from reviewable change history; explicitly disallowed by the SQL-only rule.                                                                                |

---

## 3.4. D. Agent & AI Plane

### 3.4.1. D.1 Agent Orchestration — LangGraph

**Decision:** LangGraph over CrewAI, AutoGen, LangChain `AgentExecutor`, or raw LLM calls

| Option                   | Tradeoff                                                                                                                                                                |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LangGraph** *(chosen)* | Explicit stateful graph, native A2A via inter-node calls with shared state, supervisor + specialist pattern, multi-turn memory. Every node/A2A call traced in LangFuse. |
| CrewAI                   | Role-based agents — less explicit control over state transitions and the A2A topology the self-care + fraud flows need.                                                 |
| AutoGen                  | Strong multi-agent conversation — heavier conversational model; overkill for deterministic graph-shaped workflows.                                                      |
| LangChain AgentExecutor  | Single-agent loop — no first-class multi-agent state graph; superseded by LangGraph in the same ecosystem.                                                              |
| Raw LLM calls            | Maximum control — re-implements orchestration, memory, retry, and tracing from scratch.                                                                                 |

---

### 3.4.2. D.2 Self-Care Chatbot — CopilotKit + AG-UI

**Decision:** CopilotKit runtime + AG-UI protocol over raw SSE, Vercel AI SDK, or a custom WebSocket protocol

| Option                            | Tradeoff                                                                                                                                                                                                                                                                   |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CopilotKit + AG-UI** *(chosen)* | Typed event stream (RunStarted, TextMessage, ToolCall, StateSnapshot, RunFinished) replaces ad-hoc SSE; `<CopilotChat>` + `useCopilotReadable` expose balance/plan/session context at render time. Chat context persisted in Valkey (`chat_context:{session_id}`, 2h TTL). |
| Raw SSE                           | Simple — untyped, no native tool-call/state-snapshot events; replaced by AG-UI for this reason.                                                                                                                                                                            |
| Vercel AI SDK                     | Capable streaming — less coupled to LangGraph state snapshots and the Python runtime we already run.                                                                                                                                                                       |
| Custom WebSocket protocol         | Full control — re-implements event typing, reconnection, and state sync that AG-UI already standardises.                                                                                                                                                                   |

---

### 3.4.3. D.3 RAG Retrieval — Milvus Hybrid (BM25 + HNSW + RRF)

**Decision:** hybrid BM25 lexical + HNSW dense with RRF rerank over dense-only, lexical-only, or cross-encoder rerank

| Option                      | Tradeoff                                                                                                                                                                                                                                     |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Hybrid + RRF** *(chosen)* | Combines keyword precision (BM25) with semantic recall (HNSW, `text-embedding-3-small` 1536d) across `faq_chunks`, `plan_vectors`, `sop_chunks`; RRF fuses at query time. RRF threshold tuned (0.1 → 0.03) so queries are not over-filtered. |
| Dense-only                  | Semantic match — misses exact plan codes/IDs and keyword-specific FAQ terms.                                                                                                                                                                 |
| BM25-only                   | Keyword match — misses paraphrase and intent similarity central to a self-care chatbot.                                                                                                                                                      |
| Cross-encoder rerank        | Strongest ranking — per-pair inference cost too high for the chatbot read path; RRF gives the recall/latency balance needed.                                                                                                                 |

---

### 3.4.4. D.4 LLM Provider — Azure OpenAI (Target Path: Amazon Bedrock)

**Decision:** Azure OpenAI (GPT-5.4 / GPT-5.4-mini, `text-embedding-3-small`) over Bedrock, OpenAI direct, or self-hosted OSS

| Option                      | Tradeoff                                                                                                                                                                           |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Azure OpenAI** *(chosen)* | Enterprise controls, established SDK, model quality for agents and embeddings. LLM calls are kept off the hot path and the LLM-discovery sample is hard-capped at 100 subscribers. |
| Amazon Bedrock              | Available in `ap-south-1` (Titan / Claude) — resolves the residency gap below; **target-state path** to evaluate for India data residency.                                         |
| OpenAI (direct)             | Same models — weaker enterprise/data-processing controls than Azure; no residency advantage.                                                                                       |
| Self-hosted OSS (vLLM)      | Full control + residency — large GPU ops cost and lower out-of-box quality vs frontier models.                                                                                     |

> **Accepted risk:** Azure OpenAI is not available in India; any prompt containing subscriber-identifiable context is a residency exposure. Mitigated by PII hygiene (subscriber UUID, not MSISDN; anonymised CDR stats). Target-state remedy is Amazon Bedrock in `ap-south-1`.

---

### 3.4.5. D.5 Fraud Detection — Rule Pre-Screener + Async LangGraph (Off Hot Path)

**Decision:** deterministic pre-screener (synchronous) + async LangGraph LLM escalation over synchronous LLM, pure rules, or a trained ML classifier

| Option                                  | Tradeoff                                                                                                                                                                                                                                                      |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Pre-screener + async LLM** *(chosen)* | Fast deterministic rules flag synchronously; LLM confirmation runs async on `cdr.fraud.flagged`, strictly off the balance P95 path. Inputs: CDR + triggered rules + 7-day subscriber history; outputs confirmed/false_positive/needs_review → `fraud.alerts`. |
| Synchronous LLM on hot path             | Best fraud latency — LLM call inside the deduction path blows the 200ms P95 budget.                                                                                                                                                                           |
| Pure rules (no LLM)                     | Cheap and fast — misses nuanced fraud patterns the LLM escalation is there to catch.                                                                                                                                                                          |
| Trained ML classifier                   | Strong signal — requires labelled data and MLOps not available at this stage; architecture hook retained for production.                                                                                                                                      |

> **Accepted risk:** the async flow leaves a 5–15s window where fraudulent CDRs continue processing while the LLM confirms. Target-state remedy: on pre-screener FLAG, write a soft-suspend `suspect:{msisdn}` Valkey key before escalation.

---

### 3.4.6. D.6 ML Forecasting — Deferred Model Choice (Baseline in MVP)

**Decision:** defer the deep-learning model choice (TimesFM / Chronos / Prophet / NeuralForecast) to post-MVP; ship a scikit-learn baseline over committing to one DL model now

| Option                                       | Tradeoff                                                                                                                               |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Defer + scikit-learn baseline** *(chosen)* | MVP gets simple linear/gradient-boost forecasts now; the DL model is selected against real forecast error once production data exists. |
| Commit to TimesFM now                        | Strong transformer forecasts — premature lock-in before the data distribution and error baseline are known.                            |
| Commit to Prophet now                        | Mature and simple — weaker on the multi-seasonal telecom patterns the DL candidates target.                                            |
| Commit to NeuralForecast now                 | Broadest model zoo — heaviest dependency and tuning surface; revisit with data.                                                        |

---

## 3.5. E. Auth & Security

### 3.5.1. E.1 Identity Provider — Keycloak (Self-hosted on EKS)

**Decision:** Keycloak over AWS Cognito, Auth0, or a custom JWT service

| Option                  | Tradeoff                                                                                                                                                                                                                                        |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Keycloak** *(chosen)* | Enterprise RBAC and realm/client control the scale warrants; self-hosted on EKS keeps auth data inside `ap-south-1`. Same JWT structure and `role` claims as the MVP. 30-min access-token TTL bounds the blacklist enforcement gap to ≤ 30 min. |
| AWS Cognito             | MVP choice (via MiniStack) — sufficient at MVP scale; thinner enterprise RBAC and less control than a full IdP at target scale.                                                                                                                 |
| Auth0                   | Managed IdP — SaaS data residency constraints and per-MAU cost; no advantage over self-hosted Keycloak given EKS is already required.                                                                                                           |
| Custom JWT service      | Maximum control — re-implements OTP, token issuance, revocation, and role management that an IdP provides.                                                                                                                                      |

---

### 3.5.2. E.2 Blacklist Enforcement — Postgres + IdP (No Redis Cache)

**Decision:** `fraud_blacklist` table + IdP account disable (tokens revoked), enforced at the API Gateway JWT layer over a Redis blacklist cache or app-middleware checks

| Option                            | Tradeoff                                                                                                                                                   |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **DB + IdP + Gateway** *(chosen)* | Single source of truth (Postgres) → IdP disables the account and revokes tokens → API Gateway fails JWT validation. No dual-write, no cache/DB divergence. |
| Redis blacklist cache             | Faster lookup — introduces dual-write and sync complexity plus cache/DB divergence risk; eliminated deliberately.                                          |
| App-middleware check              | Per-service enforcement — duplicates the check across every service and races the token TTL.                                                               |
| Gateway-only blocklist            | Edge-only — no durable record or IdP-side disable; loses the audit and Cognito/Keycloak revocation side effects.                                           |

---

### 3.5.3. E.3 PII & PCI-DSS Controls — Layered (pgcrypto + Tokenisation + Redaction)

**Decision:** layered controls — pgcrypto AES-256 columns, simulated PAN tokenisation at entry, Fluentd PII redaction, INSERT-only audit role, TLS 1.2+ at ALB/Gateway — over app-only encryption or a single control

| Option                          | Tradeoff                                                                                                                                                                                                               |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Layered controls** *(chosen)* | Defence in depth: PII encrypted at rest (pgcrypto), raw PAN never persisted (tokenised at point of entry), PII stripped from logs (Fluentd redaction), audit is INSERT-only. Each layer covers another's failure mode. |
| App-layer encryption only       | Simplest — leaves logs, replicas, and backups exposed if any path bypasses the app encrypt call.                                                                                                                       |
| KMS-only (no column encryption) | Centralised key management — does not encrypt the column payload itself; relies on storage encryption that does not satisfy field-level PII requirements.                                                              |
| Network/TLS only                | Protects in transit — does nothing for at-rest PII or log leakage.                                                                                                                                                     |

---

## 3.6. F. Frontend

### 3.6.1. F.1 Frontend SPA — React 18 + Vite + Tailwind

**Decision:** single React SPA with role-based routing over Next.js, micro-frontends, or a separate app per role

| Option                          | Tradeoff                                                                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Single React SPA** *(chosen)* | One build output, four role route subtrees (`/subscriber`, `/ops`, `/fraud`, `/simulator`); JWT `role` claim gates routes. Vite for fast builds, Tailwind utility-only CSS. |
| Next.js                         | SSR/routing — SSR buys little for an authenticated dashboard behind a CDN; adds a Node runtime to a static-asset target.                                                    |
| Micro-frontends                 | Independent team scaling — coordination/shell overhead unjustified for one team and a shared design system.                                                                 |
| App-per-role                    | Strong isolation — duplicated auth/build/CI and shared-component drift across four builds.                                                                                  |

---

### 3.6.2. F.2 State Management — TanStack Query, No Global Store

**Decision:** TanStack Query (server state) + local component state; no Redux/Zustand over a global client store

| Option                                | Tradeoff                                                                                                                                                       |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **TanStack Query + local** *(chosen)* | Server state (caching, background refresh, stale data) handled by React Query; role-separated dashboards have no shared state, so a global store adds nothing. |
| Redux Toolkit                         | Mature global store — boilerplate and indirection for state that is either server-derived or component-local.                                                  |
| Zustand / Jotai                       | Lighter global stores — still unnecessary when dashboards do not share state.                                                                                  |
| Context-only                          | Built-in — re-render and scaling issues for non-trivial server cache; React Query is purpose-built for it.                                                     |

---

### 3.6.3. F.3 Real-Time UI Channels — Per-Channel Transport (WebSocket + AG-UI + Polling)

**Decision:** transport chosen per channel — WebSocket (fraud feed, notification portal, simulator trace), AG-UI (chatbot), polling/SSE (balance) over a single transport for all

| Option                               | Tradeoff                                                                                                                                                               |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Per-channel transport** *(chosen)* | Each service pushes on its own Kafka consumer over the right channel: WebSocket for server-pushed feeds, AG-UI for agent streaming, 500ms polling for balance display. |
| WebSocket for everything             | Uniform — over-engineers simple read-after-write balance updates that polling serves fine.                                                                             |
| SSE for everything                   | One-way — wrong for the bidirectional agent/chat surface and awkward for multi-event feeds.                                                                            |
| Polling only                         | Simplest — misses the push semantics the fraud/notification/simulator feeds require.                                                                                   |

---

### 3.6.4. F.4 CDN — AWS CloudFront

**Decision:** CloudFront (S3 origin, `ap-south-1`, global PoPs) over S3 static hosting, Cloudflare, or no CDN

| Option                    | Tradeoff                                                                                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CloudFront** *(chosen)* | Static-asset caching with global PoPs for low-latency delivery; origin = S3 in `ap-south-1`; SPA 403/404 → `index.html` 200 for client routing; OAC + ACM TLS. |
| S3 static hosting         | Simple — no edge caching and no global PoP latency benefit.                                                                                                    |
| Cloudflare                | Strong CDN — another vendor boundary and data path outside the AWS residency footprint.                                                                        |
| No CDN (origin only)      | Lowest cost — higher latency and origin load for a globally served static bundle.                                                                              |

---

## 3.7. G. Observability

### 3.7.1. G.1 Infra Telemetry — OTEL → LGTM (Grafana / Loki / Tempo / Mimir)

**Decision:** OTEL SDK → Collector DaemonSet → Grafana Tempo/Mimir/Loki over Datadog, Elastic APM, or Prometheus+Jaeger-only

| Option                         | Tradeoff                                                                                                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **OTEL → LGTM** *(chosen)*     | Vendor-neutral instrumentation (OTEL SDK in every service), one stack for traces/metrics/logs, Mumbai-hosted. Trace ID propagated via Kafka headers and `traceparent` across service calls. |
| Datadog / New Relic (SaaS APM) | Turnkey — SaaS egress conflicts with residency and carries per-host pricing at scale.                                                                                                       |
| Elastic APM                    | Capable — heavier Elasticsearch footprint; redundant given the LGTM stack already covers logs.                                                                                              |
| Prometheus + Jaeger (only)     | Open-source metrics + traces — no unified log tier and weaker trace/log correlation than the LGTM single-pane setup.                                                                        |

---

### 3.7.2. G.2 Agent Telemetry — LangFuse (Self-hosted on EKS)

**Decision:** LangFuse over LangSmith, Phoenix/Arize, or OTEL-GenAI-only

| Option                   | Tradeoff                                                                                                                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LangFuse** *(chosen)*  | Purpose-built for LLM/agent traces: every LangGraph node, A2A call, RAG retrieval (query + chunks + scores), and LLM call (prompt, completion, tokens, latency), plus LLM-as-Judge evals. Self-hosted for residency/cost. |
| LangSmith                | Tight LangChain integration — SaaS, residency and per-trace cost concerns at volume.                                                                                                                                      |
| Phoenix / Arize          | Strong eval/observability — overlaps with LangFuse; another operator surface.                                                                                                                                             |
| OTEL GenAI semantic only | Standard spans — lacks the agent/RAG/eval-specific UI and scoring LangFuse provides out of the box.                                                                                                                       |

---

### 3.7.3. G.3 Log Routing — Fluentd DaemonSet

**Decision:** Fluentd DaemonSet → Loki (with PII redaction filter) over Fluent Bit, Vector, or Promtail

| Option                 | Tradeoff                                                                                                                                     |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fluentd** *(chosen)* | DaemonSet ships pod logs to Loki with the same config from MVP to target; redaction filter strips MSISDN/name/address **before** forwarding. |
| Fluent Bit             | Lighter C cousin — would require re-authoring the existing Fluentd redaction pipeline; chosen where the config already exists.               |
| Vector                 | High-performance Rust router — another toolchain; no functional gap it closes here.                                                          |
| Promtail               | Loki-native — narrower plugin/redaction ecosystem than Fluentd.                                                                              |

---

## 3.8. H. Infrastructure & Platform

### 3.8.1. H.1 Container Orchestration — AWS EKS

**Decision:** EKS over ECS Fargate, EC2+systemd, App Runner, or Nomad

| Option             | Tradeoff                                                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **EKS** *(chosen)* | Service-level scaling for ~18 services/agents; hosts the self-managed workloads the architecture requires (Milvus Distributed, Keycloak, LangFuse). Mumbai. |
| ECS Fargate        | Managed, no control plane — cannot run Milvus Distributed / custom operator workloads as cleanly; less portable than Kubernetes.                            |
| EC2 + systemd      | Maximum control — operator owns scheduling, rollout, scaling, and self-healing for 18 services; unjustified.                                                |
| App Runner         | Simplest for web services — no support for long-lived Kafka consumers or stateful workloads.                                                                |
| Nomad              | Capable scheduler — smaller ecosystem and talent pool than Kubernetes; no advantage.                                                                        |

---

### 3.8.2. H.2 IaC — Terraform

**Decision:** Terraform (S3 + DynamoDB state, modular) over CloudFormation, CDK, Pulumi, or manual console

| Option                   | Tradeoff                                                                                                                                                                                                               |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Terraform** *(chosen)* | All target AWS infra as code (10 modules: networking, eks, rds, msk, elasticache, cognito, s3, cloudfront, api_gateway, secrets). Outputs feed `pydantic-settings` via Secrets Manager. Applied before any app deploy. |
| CloudFormation           | Native AWS — more verbose YAML/JSON, weaker module reuse than Terraform's ecosystem.                                                                                                                                   |
| AWS CDK                  | Code-defined infra — couples infra to a language/runtime and adds a synthesis step.                                                                                                                                    |
| Pulumi                   | Code-defined infra — capable; Terraform chosen for broader provider/module maturity and team familiarity.                                                                                                              |
| Manual console           | Fastest first step — no reviewable, repeatable environment; explicitly rejected.                                                                                                                                       |

---

### 3.8.3. H.3 Cloud & Region — AWS, `ap-south-1` Single-Region

**Decision:** single-region AWS `ap-south-1` over multi-region active-active, multi-cloud, or on-prem

| Option                                  | Tradeoff                                                                                                                                                                      |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Single-region ap-south-1** *(chosen)* | Satisfies TRAI India-only residency with no cross-region transfer; Multi-AZ gives HA, read replicas serve reporting. Matches the single-region, single-jurisdiction workload. |
| Multi-region active-active              | Lower DR RTO — violates residency (cross-region transfer) and multiplies cost for a single-jurisdiction dataset.                                                              |
| Multi-cloud                             | Vendor diversification — breaks managed-service integration (MSK, RDS, ElastiCache) and adds cross-cloud networking/egress complexity.                                        |
| On-prem                                 | Maximum residency control — loses managed-service economics and shifts all ops burden in-house.                                                                               |

---

## 3.9. I. Cross-cutting

### 3.9.1. I.1 Config Management — Pydantic-settings

**Decision:** pydantic-settings (eager load, fail-fast; env / `.env` / Secrets Manager) over dotenv-only, dynaconf, or raw `os.environ`

| Option                           | Tradeoff                                                                                                                                                            |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **pydantic-settings** *(chosen)* | Typed, validated config with a single source; eager load fails fast on misconfig; Terraform outputs injected via Secrets Manager. Used with `pytest-env` for tests. |
| python-dotenv only               | Loads env — no type validation, no fail-fast on missing/malformed values.                                                                                           |
| dynaconf                         | Layered config — extra abstraction over the single env+secrets model we need.                                                                                       |
| Raw `os.environ`                 | No abstraction — scattered string parsing and no validation across services.                                                                                        |

---

### 3.9.2. I.2 Distributed Tracing — Trace ID Stamped at Ingest, Propagated Everywhere

**Decision:** a single trace ID stamped at CDR ingest (plus session/trace IDs on the portal), propagated via Kafka headers + OTEL across every stage over per-hop correlation IDs or log-only correlation

| Option                             | Tradeoff                                                                                                                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **End-to-end trace ID** *(chosen)* | One ID spans CDR → balance → fraud → notification → OTEL/LangFuse, and agent flows carry session + trace IDs across the multi-agent graph. Enables cross-boundary root-cause analysis. |
| Per-hop correlation IDs            | Localised context — loses the end-to-end span needed to trace a single CDR through the whole fan-out.                                                                                  |
| Log-only correlation               | Cheapest — reconstructable only by grepping timestamps; no causal chain across async/Kafka boundaries.                                                                                 |
| No tracing                         | None — unacceptable for a 100K eps pipeline with compliance audit needs.                                                                                                               |

---

### 3.9.3. I.3 Payment & Notification Gateways — Simulated (Deferred to Production)

**Decision:** simulated payment + OTP published to the `notification.events` Kafka stream (no real gateway) over integrating real gateways now

| Option                                    | Tradeoff                                                                                                                                                                                  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Simulated + deferred** *(chosen)*       | Payment fully simulated; login OTP issued via the IdP custom-auth flow and surfaced on the Notification Portal. Architecture hooks retained for real gateways. *(Explicit PRD deferral.)* |
| Real gateways now (Twilio/MSG91/Razorpay) | Production parity — pulls in vendor contracts, credential ops, and compliance scope the build does not need yet.                                                                          |

---

*Target-state stack reference: [architecture.md §1.3.2](bmad_output/planning-artifacts/architecture.md#132-decided-stack--target-state). CDR-pipeline deep dive: [Event Stream and CDR Pipeline.md](decision_logs/Event%20Stream%20and%20CDR%20Pipeline.md).*
