---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - docs/bmad_output/planning-artifacts/prds/prd-sboai_capstone-2026-06-18/prd.md
  - docs/decision_logs/Event Stream and CDR Pipeline.md
workflowType: 'architecture'
project_name: 'sboai_capstone'
user_name: 'shyam'
date: '2026-06-18'
lastStep: 8
status: 'complete'
completedAt: '2026-06-18'
---

# 1. Architecture Decision Document

## 1.1. AI-Powered Prepaid Billing System

---

## 1.2. Project Context Analysis

### 1.2.1. Requirements Overview

**Functional Requirements — 77 FRs across 14 domains:**

| Domain                     | FRs      | Key Architectural Driver                                 |
| -------------------------- | -------- | -------------------------------------------------------- |
| Account & Identity         | FR-1–7   | Auth service, KYC state machine, OTP pipeline            |
| Balance & Usage            | FR-8–11  | Real-time read path, CDR-triggered write buffer          |
| Recharge & Payments        | FR-12–17 | Idempotent payment flow, PDF receipt gen                 |
| Notifications              | FR-18–21 | Event-driven, threshold-triggered, simulated delivery    |
| Self-Care Chatbot          | FR-22–36 | Multi-agent orchestration, RAG, A2A, AG-UI, LangGraph    |
| USSD Interface             | FR-37–41 | Stateful callback handler, session store in Valkey/Redis |
| Ops & Marketing Dashboard  | FR-42–52 | Materialised views, time-series ML, LLM segmentation     |
| Fraud Management Dashboard | FR-53–56 | Real-time anomaly feed, case queue, WebSocket push       |
| CDR Ingestion Pipeline     | FR-57–59 | Streaming backbone, 100K eps target, DLQ                 |
| Fraud Detection Agent      | FR-60–62 | Async LLM escalation off the balance hot path            |
| Security & Compliance      | FR-63–67 | PII encryption, PCI-DSS tokenisation, TRAI, JWT roles    |
| Simulator & Dev Tools      | FR-68–70 | CDR generator, notification observer, trace display      |
| Synthetic Dataset          | FR-71    | 300K subscribers, 5M CDRs, seed scripts                  |
| Eval, Observability, QA    | FR-72–77 | LangFuse, DeepEval, LLM-as-Judge, OTEL trace propagation |

**Non-Functional Requirements:**

| NFR                       | Target                 | Architecture Implication                           |
| ------------------------- | ---------------------- | -------------------------------------------------- |
| Balance deduction latency | P95 ≤ 200ms            | Valkey write buffer; agents strictly off hot path  |
| CDR throughput (Target)   | 100,000 eps            | 24-partition Kafka/Redpanda; Rust consumer workers |
| CDR throughput (MVP)      | ~10,000 eps            | Redpanda + aiokafka; Python consumer               |
| Idempotency               | Exactly-once deduction | Valkey SET on `cdr_record_id`, 24h TTL             |
| Data localisation         | India only             | AWS `ap-south-1` (Mumbai) for all target infra     |
| Audit retention           | 6 years (TRAI)         | Immutable Postgres audit log; archival to S3       |
| PCI-DSS                   | Card tokenisation      | Raw PAN never persisted; tokenised reference only  |
| PII                       | AES-256 at rest        | Encrypted columns; PII never in logs               |
| Auth                      | JWT + OTP step-up      | 4 role-separated dashboards                        |

**Scale & Complexity:** Enterprise. ~18 services/agents. Two deployment contexts: MVP (local Docker Compose / MiniStack) and Target State (AWS EKS, Mumbai).

### 1.2.2. Technical Constraints

- Fraud/conclusion/notification agents **must** be async to balance deduction
- All subscriber data physically in India (TRAI mandate)
- Vector store: **Milvus** — fixed for both MVP and Target State
- MVP DB: **PostgreSQL** — fixed
- LLM discovery sample hard-capped at 100 subscribers per upselling session
- Payment is fully simulated — no real gateway in MVP
- USSD is inbound callback only — system never initiates USSD sessions

### 1.2.3. Cross-Cutting Concerns

| Concern               | How Addressed                                                                                                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Distributed trace ID  | Propagated CDR → balance → fraud → notification → OTEL (to LangFuse/OTEL-TUI/LGTM);<br>Similarly, for agents, Session and Trace ID need to be distributed in the multi-agent workflow |
| Idempotency           | Recharge guard (idempotency key) + CDR deduction (Valkey SET) + notification (once-per-event flag)                                                                                    |
| Async agent execution | Fraud, Conclusion, Notification agents publish to Kafka topic post-deduction; never in P95 path                                                                                       |
| Role-based auth       | JWT with `role` claim; 4 dashboards (Subscriber, Ops, Fraud, Simulator)                                                                                                               |
| Event-driven backbone | CDR ingestion fans out to balance, fraud-screening, and notification in parallel                                                                                                      |
| PII hygiene           | AES-256 at rest; Postgres encrypted columns; stripped from all OTEL/Fluentd log pipelines                                                                                             |

---

## 1.3. Technology Stack

### 1.3.1. Decided Stack — MVP

| Layer                      | Technology                          | Rationale                                                                     |
| -------------------------- | ----------------------------------- | ----------------------------------------------------------------------------- |
| **CDR Pipeline**           | Python (aiokafka consumer workers)  | Single-language MVP; sufficient for 10K eps PoC                               |
| **Application Backend**    | Python 3.14 + FastAPI               | All non-pipeline services in one FastAPI monorepo                             |
| **DB Client**              | Psycopg3 (async) + connection pool  | Native async protocol; binary mode; faster than asyncpg for most workloads; SQL-only, no ORM |
| **DB Migrations**          | Flyway (SQL-native)                 | All schema DDL, views, materialized views, triggers managed as versioned SQL migrations |
| **Event Bus**              | Redpanda (Kafka-compatible, Docker) | No ZooKeeper; Kafka-wire-compatible; simpler MVP ops                          |
| **Balance Write Buffer**   | Valkey (Docker, MVP)                | Fast atomic INCRBY; session store; dedup SET; Redis-compatible; |
| **Primary Database**       | PostgreSQL 16                       | Source of truth for balance, accounts, audit, plans                           |
| **Vector Store**           | Milvus (Docker)                     | Fixed. Hybrid search: dense + BM25 + RRF reranker                             |
| **Agent Orchestration**    | LangGraph (Python)                  | Stateful graph, native A2A, multi-turn memory                                 |
| **LLM Provider**           | Azure OpenAI                        | GPT-5.4-mini and GPT-5.4 for agents; `text-embedding-3-small` for embeddings  |
| **Frontend**               | React 18 + Vite + TailwindCSS       | Fast builds; single SPA with role-based routing                               |
| **Chatbot UI**             | CopilotKit (`@copilotkit/react-ui`) | `<CopilotChat>` component; AG-UI event stream replacing SSE                   |
| **Agent–UI Protocol**      | AG-UI (via CopilotKit runtime)      | Typed event stream: tool calls, state snapshots, text deltas                  |
| **Config Management**      | pydantic-settings                   | Unified env / `.env` / Secrets Manager config; eager load; fails fast         |
| **Auth**                   | AWS Cognito (via MiniStack)         | JWT issuance; OTP via Cognito; role claims in token                           |
| **Observability (infra)**  | OTEL-TUI (Docker)                   | Low memory footprint; traces/logs/metrics in terminal                         |
| **Observability (agents)** | LangFuse (self-hosted Docker)       | All agent/tool calls traced                                                   |
| **Log routing**            | Fluentd                             | Routes Docker logs to OTEL-TUI (MVP) or LGTM (Target)                         |
| **PDF Generation**         | WeasyPrint (Python)                 | HTML→PDF for receipts; no headless browser dep                                |
| **ML Forecasting**         | scikit-learn                        | Subscriber growth/plan popularity; simple linear/gradient-boost               |
| **CI/CD**                  | GitHub Actions                      | PR checks, lint, test, Docker build                                           |
| **Container**              | Docker Compose                      | All services including Redpanda, Milvus, Redis, Postgres, LangFuse, MiniStack |
| **CDR Simulator**          | Python Scripts                      | Manually generated via a UI. Limited to 100 CDRs in 1 shot                    |

### 1.3.2. Decided Stack — Target State

| Layer                       | Technology                                                    | Rationale                                                               |
| --------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **CDR Pipeline**            | Rust (tokio + rdkafka)                                        | 100K eps; sub-200ms P95; zero-GC; max throughput on Kafka consumers     |
| **Application Backend**     | Python 3.14 + FastAPI                                         | Microservices; each domain service independently deployed               |
| **Event Bus**               | Amazon MSK (Apache Kafka)                                     | Managed, 100K eps capable, 24 partitions; `ap-south-1`                  |
| **Balance Write Buffer**    | Amazon ElastiCache Valkey                                     | Managed Redis-compatible; higher throughput than Redis                  |
| **Primary Database**        | Amazon RDS PostgreSQL (Multi-AZ)                              | Managed HA; read replicas for reporting; `ap-south-1`                   |
| **OLTP Hot Write Layer**    | Valkey INCRBY → async bulk upsert → RDS                       | As per decision log: Valkey absorbs write spikes; RDS for audit/SQL     |
| **Vector Store**            | Milvus (self-managed on EKS)                                  | Fixed. Same Milvus collection schema as MVP; scaled replicas            |
| **Agent Orchestration**     | LangGraph (Python)                                            | Unchanged from MVP                                                      |
| **LLM Provider**            | Azure OpenAI                                                  | Unchanged; consider Bedrock for future data residency                   |
| **Frontend**                | React 18 + Vite + TailwindCSS                                 | Built as static assets; S3 origin; served via CloudFront (CDN, `ap-south-1`) |
| **CDN**                     | AWS CloudFront                                                | Static asset caching; global PoPs for low-latency delivery; origin = S3 bucket |
| **Auth**                    | Keycloak (self-hosted on EKS)                                 | Enterprise RBAC; scale warrants full IdP over Cognito                   |
| **API Gateway**             | AWS API Gateway + ALB                                         | Rate limiting (FR-36); JWT validation; subscriber blacklist enforcement |
| **Observability (infra)**   | OTEL → LGTM (Grafana, Loki, Tempo, Mimir)                     | Managed Grafana on AWS; `ap-south-1`                                    |
| **Observability (agents)**  | LangFuse (self-hosted on EKS)                                 | Same as MVP; scaled deployment                                          |
| **Log routing**             | Fluentd (DaemonSet on EKS)                                    | Routes pod logs to Loki; unchanged Fluentd config from MVP              |
| **ML Forecasting**          | To be evaluated: TimesFM / Chronos / Prophet / NeuralForecast | Deep learning forecast models; choice deferred post-MVP                 |
| **Container Orchestration** | AWS EKS (Kubernetes)                                          | Service-level scaling; Milvus, Keycloak, LangFuse all on cluster        |
| **CDR Simulator**           | Rust binary (same codebase as pipeline, feature-flagged)      | Generates synthetic CDR events at target throughput for load testing    |
| **Audit Archive**           | S3 + S3 Glacier                                               | 6-year TRAI-compliant retention; lifecycle policies                     |

---

## 1.4. CDR Pipeline Architecture (Decision Log Reference)

> Full decision log: `docs/decision_logs/Event Stream and CDR Pipeline.md`

### 1.4.1. MVP Data Flow

```
CDR Source (Simulator or upstream)
  │
  ▼
Redpanda: cdr.raw  [24 partitions, key = subscriber_id]
  │
  ▼
Python Consumer Pool  [aiokafka, group_id='cdr-balance-updater']
  │  batch=500 | commit offset AFTER batch success
  │
  ├─► Dedup ──► Redis SET (cdr_record_id, TTL=24h)
  │
  ├─► Balance Update ──► Redis INCRBY pipeline (atomic)
  │                         └─► Async flush → PostgreSQL (bulk upsert, 2s or 5K)
  │
  └─► Filter & Publish ──► Redpanda: cdr.enriched.filtered
                              ├─► Fraud Pre-Screener (Kafka consumer, same Python codebase)
                              └─► Notification Trigger (Kafka consumer, same Python codebase)
```

### 1.4.2. Target State Data Flow

```
CDR Source (upstream operator)
  │
  ▼
Amazon MSK: cdr.raw  [24 partitions, key = subscriber_id]
  │
  ▼
Rust Consumer Service  [tokio + rdkafka, consumer group 'cdr-balance-updater']
  │  micro-batch=500 | at-least-once + idempotency
  │
  ├─► Dedup ──► ElastiCache Valkey SET (cdr_record_id, TTL=24h)
  │
  ├─► Balance Update ──► Valkey INCRBY pipeline
  │                         └─► Async flush → RDS PostgreSQL (bulk upsert)
  │
  └─► Publish ──► MSK: cdr.enriched.filtered
                    ├─► Fraud Pre-Screener Service (Python microservice, Kafka consumer)
                    ├─► Notification Service (Python microservice, Kafka consumer)
                    └─► Analytics/Reporting sink
```

### 1.4.3. Key Invariants (Both MVP and Target)

- Offset committed only after full batch success (at-least-once + idempotent dedup)
- Balance deduction P95 ≤ 200ms: Valkey/Redis write path; Postgres is async flush
- Fraud agent escalation runs **after** balance deduction, on `cdr.enriched.filtered` topic
- FastAPI = management plane only (DLQ inspection, worker pause/resume, metrics) — never on record hot path
- Dead-Letter Queue: `cdr.dlq` topic; poison records isolated; manual replay via DLQ inspector API
- Trace ID stamped at CDR ingest; propagated through all downstream stages
- Session & Trace IDs are also stamped for all interactions on the self-serve portal (incl agentic workflows)

---

## 1.5. Service Architecture

### 1.5.1. MVP — Two-Codebase Structure

**MVP uses two primary codebases** (no inter-service HTTP calls between them):

```
sboai_capstone/
├── cdr-pipeline/          # CDR ingestion + balance engine + fraud pre-screener
│   (Python, aiokafka, Redpanda, Redis, Postgres)
│
└── app-backend/           # All other backend: API, agents, notifications, USSD
    (Python, FastAPI, LangGraph, Milvus, Postgres, Redis)
```

All non-CDR domain logic (auth, accounts, balance reads, recharge, chatbot agents, USSD, notifications, dashboards, fraud case management, ML forecasting) lives in `app-backend` as FastAPI routers and internal Python modules. No HTTP between the two codebases — they share Postgres and Redis.

### 1.5.2. Target State — Microservices

| Service                | Language                         | Responsibility                                                                       |
| ---------------------- | -------------------------------- | ------------------------------------------------------------------------------------ |
| `cdr-ingestion`        | Rust                             | Kafka consumer; dedup; Valkey balance write; fan-out                                 |
| `account-service`      | Python/FastAPI                   | Registration, KYC, SIM activation, profile                                           |
| `balance-service`      | Python/FastAPI                   | Balance reads, usage, plan details, transaction history                              |
| `recharge-service`     | Python/FastAPI                   | Plan catalogue, payment sim, idempotent recharge, PDF receipt                        |
| `notification-service` | Python/FastAPI                   | Threshold checks, simulated SMS/push, Notification Portal                            |
| `chatbot-service`      | Python/FastAPI + LangGraph       | Multi-agent orchestration: Support, Rating, Balance, Conclusion, Notification agents |
| `ussd-service`         | Python/FastAPI                   | USSD callback handler, session state via Valkey                                      |
| `fraud-service`        | Python/FastAPI + LangGraph       | Pre-screener consumer + Fraud Detection Agent                                        |
| `ops-service`          | Python/FastAPI                   | Ops dashboard APIs: plan stock, order fulfilment, forecasts, segmentation            |
| `auth-service`         | Keycloak                         | JWT issuance, OTP, role management                                                   |
| `simulator-service`    | Rust (shared with cdr-ingestion) | CDR event generator, trace viewer                                                    |
| `eval-service`         | Python                           | DeepEval, LLM-as-Judge, offline eval runner                                          |

---

## 1.6. Agent Architecture

### 1.6.1. Self-Care Chatbot (LangGraph)

```
Subscriber Browser
  │  (AG-UI event stream over HTTP POST /chat/stream)
  ▼
CopilotKit Runtime  (FastAPI endpoint, copilotkit Python SDK)
  │  emits AG-UI events: RunStarted, TextMessageStart/Content/End,
  │                       ToolCallStart/Args/End, StateSnapshot, RunFinished
  ▼
Support Agent  (LangGraph supervisor node)
  ├── Tool: balance_lookup  ──► Balance Management Agent
  ├── Tool: charge_explain  ──► Rating Agent
  ├── Tool: rag_search      ──► Milvus (hybrid: dense + BM25 + RRF)
  ├── Tool: recharge_flow   ──► Link for Recharging in portal
  ├── Tool: ticket_create   ──► Postgres (support_tickets table)
  ├── Tool: recommend_plan  ──► Plan Recommendation (hybrid search + usage signals)
  │
  └── On session end:
        └── Conclusion Agent
              └── A2A: Notification Agent ──► Kafka: notification.events
```

**Frontend — CopilotKit:**

- Library: `@copilotkit/react-ui` + `@copilotkit/react-core`
- Component: `<CopilotChat>` embedded in `/subscriber/Chatbot.tsx`
- `<CopilotKit runtimeUrl="/api/chat/stream">` wraps the subscriber portal
- AG-UI protocol replaces the prior SSE approach — all agent state, tool calls, and text deltas stream as typed AG-UI events
- `useCopilotReadable` hooks expose balance, plan, and session context to the agent at render time

**Backend — AG-UI + CopilotKit Runtime:**

- Package: `copilotkit` (Python SDK) wired into FastAPI as a router
- `POST /api/chat/stream` — CopilotKit runtime endpoint; streams AG-UI events
- LangGraph graph registered with `CopilotKitState` mixin so state transitions are surfaced as `StateSnapshot` events
- All inter-agent A2A calls traced in LangFuse with matching `trace_id`

**A2A protocol:** LangGraph inter-node calls with shared state graph. All inter-agent calls traced in LangFuse.

**RAG Pipeline:**

- Dense: `text-embedding-3-small` → Milvus HNSW index
- Sparse: BM25 lexical search with metadata filtering (plan type, category)
- Fusion: Reciprocal Rank Fusion (RRF) reranker
- Knowledge base: Telecom FAQ + plan/billing content (seeded from synthetic dataset)

**Plan Recommendation (FR-32):**

- Hybrid search on plan vectors (plan attributes encoded)
- Usage signals: pre-aggregated CDR feature summaries from Postgres materialised view
- Returns 1–3 plans; rationale surfaced in natural language
- Acceptance/dismissal logged to `recommendation_feedback` table

### 1.6.2. Fraud Detection Agent (LangGraph)

```
cdr.enriched.filtered (Kafka consumer)
  │
  ▼
Rule-Based Pre-Screener (deterministic, in-process)
  │  Rules: high voice rate, roaming abuse, SIM swap signal, suspicious recharge
  │
  ├── PASS: no action
  │
  └── FLAG: publish to cdr.fraud.flagged
              │
              ▼
        Fraud Detection Agent (LangGraph, async)
          │  Inputs: CDR event + triggered rules + subscriber history (7-day window)
          │  Output: confirmed | false_positive | needs_review
          │
          ├── confirmed → write to fraud_cases table + Kafka: fraud.alerts
          │              → Blacklist write to fraud_blacklist table (FR-66)
          │              → Cognito account disable + token revocation
          └── LangFuse trace on every escalation
```

**Subscriber history metrics analyzed (7-day window):**

| Metric                                                | Source                    | Fraud Signal                             |
| ----------------------------------------------------- | ------------------------- | ---------------------------------------- |
| CDR count per hour (voice / data / SMS split)         | `billing_cdr_events`      | Velocity spike vs 7d baseline            |
| Total spend rate (₹/day) vs 7d moving average         | `billing_wallet_balances` | Anomalous depletion rate                 |
| Balance depletion rate (% remaining per day)          | `billing_wallet_balances` | Unusually rapid drain                    |
| Recharge frequency and amount variance                | `recharge_orders`         | Micro-recharge churn or bulk top-up      |
| International / roaming call % of total CDRs          | `billing_cdr_events`      | Roaming abuse pattern                    |
| Unique destination numbers contacted (voice)          | `billing_cdr_events`      | High contact diversity → SIM farm signal |
| SIM swap event count                                  | `identity_registrations`  | Recent swap + activity spike             |
| Failed transaction count                              | `billing_transactions`    | Repeated payment probe pattern           |
| Peak usage hour shift (Δ from 7d modal hour)          | `billing_cdr_events`      | Ownership change indicator               |
| Cell tower location variance (if CDR carries cell ID) | `billing_cdr_events`      | Geographic anomaly                       |

### 1.6.3. Ops/Marketing Agents

```
Target Base Builder (FR-46–50):
  Marketing Manager → filter UI
    │
    ├─► SQL: materialised subscriber KPI view (dynamic columns from schema)
    ├─► Stratified Sample 100 → LLM (Azure OpenAI): per-customer segment labels
    ├─► Rule Induction Agent (LangGraph): KPI-predicate rules → Postgres
    └─► Deterministic classification of full pool (no LLM)

Upsell Strategy Agent (FR-51):
  LLM → textual strategy per segment → logged to upsell_feedback table

Root Cause Analysis Agent (FR-75):
  LLM + RAG (SOP knowledge base + audit_log + CDRs)
    └─► Structured root cause analysis output
```

---

## 1.7. Data Architecture

### 1.7.1. PostgreSQL Table Naming

**Single `public` schema — domain prefix convention.** Separate PostgreSQL schemas (`identity.*`, `billing.*` etc.) are avoided in MVP; they add cross-schema permission management overhead without meaningful benefit at this scale. Domain is encoded as a table name prefix instead.

**Naming pattern:** `{domain}_{table_name}` — all in `public` schema.

| Domain prefix    | Tables                                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `identity_`      | `identity_subscribers`, `identity_registrations`, `identity_kyc_records`, `identity_caf_submissions`                                                                           |
| `billing_`       | `billing_wallet_balances`, `billing_cdr_events`, `billing_transactions`, `billing_audit_log`                                                                                   |
| `plans_`         | `plans_plans`, `plans_subscriptions`, `plans_plan_config`                                                                                                                      |
| `recharge_`      | `recharge_orders`, `recharge_payment_methods`, `recharge_receipts`                                                                                                             |
| `notifications_` | `notifications_events`, `notifications_config`, `notifications_preferences`                                                                                                    |
| `support_`       | `support_tickets`, `support_chat_sessions`, `support_session_learnings`                                                                                                        |
| `fraud_`         | `fraud_cases`, `fraud_rules`, `fraud_blacklist`                                                                                                                                |
| `segmentation_`  | `segmentation_segment_rules`, `segmentation_labels`, `segmentation_recommendation_feedback`, `segmentation_upsell_feedback`; materialized view: `segmentation_subscriber_kpi_r_mvw` |
| `ops_`           | `ops_order_fulfilment`, `ops_forecast_results`                                                                                                                                 |
| `sop_`           | `sop_rules`, `sop_knowledge_chunks`                                                                                                                                            |

**Migration path to Target State:** if separate schemas become warranted at scale, migrations can rename tables and reassign schema — prefix naming makes the mapping unambiguous.

**Audit log (FR-59):** Append-only (`INSERT` only; no `UPDATE`/`DELETE` via app role). Retained 6 years; archived to S3 after 2 years via pg_partman + lifecycle policy.

**Table standards (applies to every table):**

- `id UUID DEFAULT gen_random_uuid() PRIMARY KEY`
- `created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL`
- `modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL` — updated via `set_modified_at()` trigger (defined once in a base migration, applied per table)

---

### 1.7.1a. Database Migration Management

**Tool: Flyway (SQL-native).** All schema evolution — initial table creation, indexes, views, materialized views, triggers, grants — is managed as versioned SQL migration files. No ORM-generated DDL. No ad-hoc schema changes outside migrations.

**Migration file location:**

```
app-backend/db/migrations/
  V1__baseline_schema.sql          # all domains: CREATE TABLE, indexes, FK constraints
  V2__set_modified_at_trigger.sql  # trigger function + application to all tables
  V3__segmentation_kpi_mvw.sql     # materialized view + refresh function
  V4__billing_views.sql            # billing_usage_summary_i_vw, etc.
  V5__seed_plans.sql               # static plan catalogue data
  ...
```

**Encoding in migrations:**

| DDL Object         | Encoded in migrations?  | Notes                                                                 |
| ------------------ | ----------------------- | --------------------------------------------------------------------- |
| Tables             | ✅ Yes                  | All domains in V1 baseline                                            |
| Indexes            | ✅ Yes                  | Co-located with table DDL; follow access-pattern rules                |
| FK constraints     | ✅ Yes                  | Explicit `REFERENCES` clauses in CREATE TABLE                         |
| Views (`_vw`)      | ✅ Yes                  | `CREATE OR REPLACE VIEW` in dedicated migration                       |
| Materialized views | ✅ Yes                  | `CREATE MATERIALIZED VIEW` + `CREATE UNIQUE INDEX` for concurrent refresh |
| Triggers           | ✅ Yes                  | `modified_at` trigger function + `CREATE TRIGGER` per table           |
| Grants / roles     | ✅ Yes                  | App role grants (read-only on audit tables, etc.)                     |
| Alembic            | ❌ Removed              | Replaced by Flyway SQL-native approach                                |

**SQL-only rule:** All database queries in application code use raw SQL strings (via psycopg3). No SQLAlchemy ORM, no Django ORM, no query builder. CQRS split (`queries.py` / `commands.py`) organises SQL by read vs. write — see §1.12.1.

**`modified_at` trigger pattern (defined once in V2 migration):**

```sql
CREATE OR REPLACE FUNCTION set_modified_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.modified_at = NOW();
  RETURN NEW;
END;
$$;

-- Applied to each table that has modified_at:
CREATE TRIGGER trg_identity_subscribers_modified_at
  BEFORE UPDATE ON identity_subscribers
  FOR EACH ROW EXECUTE FUNCTION set_modified_at();
```

### 1.7.2. Valkey / Redis Data Domains

| Key Pattern                 | Type            | TTL  | Purpose                    |
| --------------------------- | --------------- | ---- | -------------------------- |
| `dedup:{cdr_record_id}`     | SET             | 24h  | Idempotency guard          |
| `balance:{msisdn}`          | STRING (INCRBY) | None | Hot write buffer           |
| `session:{session_id}`      | HASH            | 30m  | USSD session state         |
| `otp:{msisdn}`              | STRING          | 5m   | Step-up OTP validation     |
| `chat_context:{session_id}` | HASH            | 2h   | Chatbot multi-turn context |

**Design rationale — key decisions:**

- **`balance:{msisdn}` — no TTL (intentional):** The key is a persistent running counter. CDR consumers call `INCRBY` continuously; the background flusher reads the current value and bulk-upserts it to PostgreSQL every 2s or 5K records. The key is never deleted after a flush — it keeps accumulating as the live write buffer. 300K subscribers × ~50 bytes ≈ 15MB total memory, well within Redis limits. `maxmemory-policy noeviction` must be set so Redis never evicts this key class.

- **`otp:{msisdn}` — step-up auth, not login OTP:** Initial login OTP is handled entirely by Cognito's auth flow. The Redis OTP key is for mid-session step-up verification (e.g., SIM binding change, high-value recharge above threshold). Cognito's Custom Auth Flow cannot cleanly interrupt an already-authenticated session for a second factor — Redis OTP fills this gap with a simple generate/validate/expire cycle.

- **Blacklist — Postgres + Cognito only (no Redis cache):** When a subscriber is blacklisted (e.g., confirmed SIM swap fraud), the `fraud_blacklist` table is written as the source of truth, and the subscriber's Cognito account is immediately disabled with all active tokens revoked via the Cognito admin API. Subsequent API Gateway calls fail at the JWT validation layer — Cognito returns an invalid-token response before the request reaches any backend service. This eliminates the Redis enforcement cache entirely: no dual-write, no sync complexity, no risk of cache/DB divergence.

- **Rate limiting — not in MVP; API Gateway in Target State:** MVP has no per-subscriber rate limiting. In Target State, AWS API Gateway enforces the business-level per-subscriber limit (FR-36) natively — no application-layer Redis key needed.

### 1.7.3. Milvus Collections

| Collection     | Embedding Model        | Dimensions | Metadata Fields                     |
| -------------- | ---------------------- | ---------- | ----------------------------------- |
| `faq_chunks`   | text-embedding-3-small | 1536       | category, source_doc, plan_type     |
| `plan_vectors` | text-embedding-3-small | 1536       | plan_id, plan_type, price, validity |
| `sop_chunks`   | text-embedding-3-small | 1536       | rule_id, severity, domain           |

Index type: HNSW. BM25 lexical index on same collections for hybrid search. RRF reranker at query time.

### 1.7.4. Kafka / Redpanda Topics

| Topic                   | Partitions | Key             | Consumers                                               |
| ----------------------- | ---------- | --------------- | ------------------------------------------------------- |
| `cdr.raw`               | 24         | `subscriber_id` | cdr-balance-updater consumer group                      |
| `cdr.enriched.filtered` | 24         | `subscriber_id` | fraud-pre-screener, notification-trigger                |
| `cdr.fraud.flagged`     | 6          | `msisdn`        | fraud-detection-agent                                   |
| `fraud.alerts`          | 6          | `msisdn`        | fraud-dashboard (WebSocket relay), notification-service |
| `notification.events`   | 12         | `msisdn`        | notification-service                                    |
| `cdr.dlq`               | 6          | `cdr_record_id` | DLQ inspector (manual)                                  |

---

## 1.8. Authentication & Security Architecture

### 1.8.1. Auth Flow

**MVP:** AWS Cognito (MiniStack) issues JWTs. OTP sent via Cognito (stored in Notification Portal for testing). Roles: `subscriber`, `ops`, `fraud`, `admin/simulator`.

**Target:** Keycloak on EKS. Same JWT structure; role claims identical. API Gateway validates JWT on every request. Blacklist enforcement at API Gateway layer (FR-66).

### 1.8.2. Security Controls

| Control                  | Implementation                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| PII encryption at rest   | PostgreSQL column encryption (pgcrypto); AES-256                                                                     |
| TLS in transit           | TLS 1.2+ enforced at ALB and API Gateway                                                                             |
| PII in logs              | Fluentd redaction filter strips MSISDN, name, address fields before forwarding                                       |
| Card tokenisation        | Simulated tokenisation: raw PAN → UUID token at point of entry; raw PAN never written to DB                          |
| Rate limiting (FR-36)    | MVP: not enforced at application layer. Target State: AWS API Gateway per-role throttle                        |
| Account takeover (FR-66) | SIM swap confirmed → `fraud_blacklist` table write + Cognito account disable + all tokens revoked via Cognito admin API → subsequent JWT validation at API Gateway fails |
| TRAI data localisation   | All AWS resources in `ap-south-1`; no cross-region data transfer                                                     |
| Audit immutability       | Postgres app role: INSERT only on `audit_log`; no UPDATE/DELETE grants                                               |

---

## 1.9. Frontend Architecture

### 1.9.1. Single SPA — Role-Based Dashboard Routing

```
React 18 + Vite + TailwindCSS (single build output)
  │
  ├── /subscriber/*     → Subscriber Portal (balance, recharge, chatbot, notifications)
  ├── /ops/*            → Ops & Marketing Dashboard
  ├── /fraud/*          → Fraud Management Dashboard
  └── /simulator/*      → CDR Simulator + Notification Portal + SIM Activation
```

JWT `role` claim determines which route subtree is accessible. Role mismatch → redirect to login.

**Deployment — MVP vs Target State:**

| Context      | Serving                                                                |
| ------------ | ---------------------------------------------------------------------- |
| MVP          | Vite dev server (Docker) or nginx container serving built assets        |
| Target State | `npm run build` → static assets uploaded to S3 → served via CloudFront |

**Target State CDN (CloudFront):**

- Origin: S3 bucket in `ap-south-1` (same region as all infra)
- CloudFront distribution with `ap-south-1` as primary origin; global PoPs for low latency
- Cache behaviour: long TTL on hashed asset filenames (`/assets/*.js`); no-cache on `index.html` (entry point for SPA routing)
- HTTPS enforced; custom domain (TLS cert via ACM)
- SPA routing: CloudFront error page for 403/404 → returns `index.html` with 200 (React Router handles client-side routing)

### 1.9.2. Real-Time UI Channels

| Feature                     | Mechanism                                                                 |
| --------------------------- | ------------------------------------------------------------------------- |
| Balance display after CDR   | Polling (500ms) or SSE from balance-service                               |
| Fraud anomaly feed (FR-53)  | WebSocket — fraud-service pushes on `fraud.alerts` Kafka consumer         |
| Notification Portal (FR-69) | WebSocket — notification-service pushes on `notification.events` consumer |
| CDR Simulator trace (FR-68) | WebSocket — simulator streams per-stage trace events                      |

### 1.9.3. State Management

React Query (TanStack Query) for server state. No global client state library (Redux etc.) — role-separated dashboards have no shared state. Local component state for UI interactions.

---

## 1.10. Observability Architecture

### 1.10.1. MVP — OTEL-TUI + LangFuse + Fluentd

```
All services → OTEL SDK (Python opentelemetry-sdk)
  │
  ▼
OTEL Collector (Docker)
  ├─► OTEL-TUI  (traces, metrics, logs in terminal — low memory footprint)
  └─► LangFuse  (agent/LLM traces only)

Docker container logs → Fluentd → OTEL-TUI
```

Trace ID propagated via OTEL `traceparent` header across all service calls and Kafka message headers.

### 1.10.2. Target State — LGTM + LangFuse + Fluentd

```
All services → OTEL SDK
  │
  ▼
OTEL Collector (DaemonSet)
  ├─► Grafana Tempo  (distributed traces)
  ├─► Grafana Mimir  (metrics)
  ├─► Loki           (logs)
  └─► LangFuse       (agent/LLM traces)

Pod logs → Fluentd DaemonSet → Loki
Grafana dashboards: CDR pipeline health, balance P95, fraud escalation rate, agent quality
```

**LangFuse instrumentation coverage:**

- Every LangGraph node invocation
- Every A2A inter-agent call
- Every RAG retrieval (query + retrieved chunks + scores)
- Every LLM call (prompt, completion, token count, latency)
- LLM-as-Judge evaluations

---

## 1.11. Implementation Patterns & Consistency Rules

### 1.11.0. Configuration Management

**All application configuration is managed via `pydantic-settings` at runtime.** This covers environment variables, `.env` files, and AWS Secrets Manager secrets — all resolved at startup (eager load; missing secrets are a fatal startup error).

**Bootstrap template:** [fossy-dude/pydantic-config-mgmt-template](https://github.com/fossy-dude/pydantic-config-mgmt-template) is the reference implementation to bootstrap config management in both `cdr-pipeline` and `app-backend`.

**Pattern:**

```python
from pydantic_settings import BaseSettings, SecretsManagerSettingsSource

class DatabaseSettings(BaseSettings):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str          # resolved from Secrets Manager in Target State

class Settings(BaseSettings):
    db: DatabaseSettings
    redis_url: str
    kafka_brokers: str
    azure_openai_api_key: str
    langfuse_secret_key: str
    # ... all other config

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",   # DB__HOST maps to db.host
        env_file=".env",
        secrets_dir="/run/secrets",  # Docker secrets mount (MVP)
    )

settings = Settings()   # loaded once at module import; fails fast on missing values
```

**Source priority (lowest → highest):** defaults → `.env` file → environment variables → AWS Secrets Manager (Target State via `SecretsManagerSettingsSource`).

**Rules:**

- One `Settings` singleton per service, imported as `from core.config import settings`
- Secrets Manager integration is wired only in Target State — MVP uses `.env` + environment variables
- No config values hard-coded anywhere in source; all accessed via `settings.*`
- `.env.example` committed to repo with all keys and placeholder values; actual `.env` is gitignored

### 1.11.1. Naming Conventions

**Database:**

- Tables: `{domain}_{name}` in `public` schema, `snake_case` plural — `identity_subscribers`, `billing_cdr_events`
- Columns: `snake_case` — `subscriber_id`, `msisdn`, `created_at`
- Foreign keys: `{referenced_table_singular}_id` — `subscriber_id`, `plan_id`
- Indexes: `idx_{table}_{columns}` — `idx_identity_subscribers_msisdn`
- Primary keys: always `id UUID DEFAULT gen_random_uuid()`
- Timestamps: **every table must have** `created_at TIMESTAMPTZ DEFAULT NOW()` and `modified_at TIMESTAMPTZ DEFAULT NOW()` (kept current via `ON UPDATE` trigger in migrations)

**View naming — suffix convention:**

| Suffix         | Meaning             | Example                                  |
| -------------- | ------------------- | ---------------------------------------- |
| `_vw`          | Regular view        | `billing_usage_summary_i_vw`             |
| `_mvw`         | Materialized view   | `segmentation_subscriber_kpi_r_mvw`      |

**Confidentiality flags (part of name, before `_vw`/`_mvw`):**

| Flag | Meaning       | When to apply                                           |
| ---- | ------------- | ------------------------------------------------------- |
| `_i` | Internal      | Operational data not for external exposure              |
| `_c` | Confidential  | Sensitive business data; access restricted by role      |
| `_r` | Restricted    | Contains PII or regulated data (MSISDN, name, address)  |

Full naming pattern: `{domain}_{descriptor}_{confidentiality}_{vw|mvw}` — e.g. `segmentation_subscriber_kpi_r_mvw`, `billing_usage_summary_i_vw`.

**Index strategy (access-pattern driven):**

- Every foreign key column gets an index
- Every column used in `WHERE` clauses in expected hot queries gets an index
- Composite indexes follow query column order (most selective first)
- Indexes defined in migration files alongside table DDL — no ad-hoc index creation

**API:**

- REST endpoints: plural nouns, kebab-case — `GET /subscribers/{id}`, `POST /recharge-orders`
- Query params: `snake_case` — `?subscriber_id=`, `?page_size=`
- Path params: `{snake_case}` — `{subscriber_id}`
- Headers: `X-Trace-Id`, `X-Request-Id` (custom); standard JWT in `Authorization: Bearer`

**Python:**

- Modules/files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Pydantic models: suffix with `Request`/`Response`/`Schema` — `RechargeRequest`, `BalanceResponse`

**Kafka topics:** `domain.subdomain` dot-separated — `cdr.raw`, `cdr.enriched.filtered`, `fraud.alerts`

**React:**

- Components: `PascalCase.tsx` — `BalanceCard.tsx`, `FraudCaseQueue.tsx`
- Hooks: `usePascalCase.ts` — `useBalance.ts`, `useWebSocket.ts`
- Utility files: `camelCase.ts`
- CSS classes: TailwindCSS utility classes only; no custom CSS except `globals.css`

### 1.11.2. API Response Format

All FastAPI responses use a standard envelope:

```python
# Success
{
  "data": { ... },
  "meta": { "trace_id": "...", "timestamp": "2026-06-18T10:00:00Z" }
}

# Error
{
  "error": {
    "code": "BALANCE_INSUFFICIENT",
    "message": "Human-readable message",
    "detail": { ... }   # optional structured context
  },
  "meta": { "trace_id": "...", "timestamp": "2026-06-18T10:00:00Z" }
}
```

HTTP status codes: 200 (ok), 201 (created), 400 (client error), 401 (unauthenticated), 403 (forbidden / blacklisted), 404 (not found), 409 (conflict / duplicate), 422 (validation), 429 (rate limited), 500 (server error).

### 1.11.3. Kafka Event Schema

All Kafka messages: JSON, with envelope:

```json
{
  "event_type": "cdr.processed",
  "event_id": "uuid",
  "trace_id": "otel-traceparent",
  "timestamp": "ISO8601",
  "payload": { ... }
}
```

Trace ID always in Kafka message header `traceparent` AND in JSON body `trace_id`.

### 1.11.4. Error Handling Patterns

- FastAPI: global exception handler → standard error envelope (never raw 500)
- LangGraph agents: each node wraps in try/except; errors logged to LangFuse + returned as structured error state
- Kafka consumers: failed record → publish to `cdr.dlq`; batch offset not committed until retry exhausted
- Frontend: React Query error states + toast notifications; never raw error objects exposed to UI

### 1.11.5. PII Hygiene Rules (All Agents MUST Follow)

- Never log raw MSISDN, name, address, or card data — use `msisdn[-4:]` suffix or `[REDACTED]`
- Never include PII in OTEL span attributes — use subscriber UUID only
- Fluentd redaction filter is a safety net, not the primary guard

### 1.11.6. Testing Patterns

- Python backend: pytest; test files co-located in `tests/` per service codebase
- FastAPI: `httpx.AsyncClient` for API tests; no mocking of Postgres — use `testcontainers`
- LangGraph agents: unit test each node function independently; integration test full graph with mocked LLM (record/replay)
- Frontend: Vitest + React Testing Library; no Cypress for MVP
- Synthetic dataset (FR-71) used for all integration and ML tests

---

## 1.12. Project Structure

### 1.12.1. Monorepo Layout

**Key structural principles:**

- **Dependency Inversion:** All I/O adapters (DB, Vector Store, Cache, LLM) implement typed `Protocol` interfaces defined in `core/protocols/`. Business logic depends only on the protocol, never on the concrete library. Swapping Milvus for another vector store requires only a new adapter file — zero changes to agent or service code.
- **CQRS at DB layer:** Each domain has a `queries.py` (all `SELECT` operations, read-only) and a `commands.py` (all `INSERT`/`UPDATE`/`DELETE` operations, write-only). Routers and agents import from one or the other — never both from the same call site.
- **Async-only:** Every FastAPI route is `async def`. All I/O libraries are async: `psycopg` async with `AsyncConnectionPool` (Postgres), `valkey` async client (Valkey), `aiokafka` (Kafka), `pymilvus` async (Milvus). No blocking I/O calls anywhere in the hot path.
- **Task runner:** `justfile` (cross-platform, works on Windows / macOS / Linux via the `just` binary). Replaces Makefile.

```
sboai_capstone/
├── .github/
│   └── workflows/
│       ├── ci-pipeline.yml          # lint, test, build on PR
│       └── ci-cdr.yml               # CDR pipeline specific checks
├── docker/
│   ├── docker-compose-dependencies.yaml  # infra only: Redpanda, Redis, Postgres, Milvus, etc.
│   ├── docker-compose.yaml               # full stack: extends dependencies + app services
│   └── docker-compose.override.yaml      # local dev overrides (port mappings, hot reload)
├── .env.example
├── justfile                         # cross-platform task runner (just up, just test, etc.)
│
├── cdr-pipeline/                    # CDR ingestion codebase (MVP: Python, Target: Rust)
│   ├── pyproject.toml               # MVP Python deps (aiokafka, psycopg[async,pool], valkey[asyncio], pydantic-settings)
│   ├── src/
│   │   ├── main.py                  # Consumer entrypoint (async)
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings Settings singleton
│   │   │   └── protocols/
│   │   │       ├── db.py            # DatabaseProtocol (async read/write)
│   │   │       └── cache.py         # CacheProtocol (async get/set/incrby/expire)
│   │   ├── adapters/
│   │   │   ├── postgres.py          # Psycopg3AsyncAdapter implements DatabaseProtocol (AsyncConnectionPool)
│   │   │   └── redis.py             # RedisAdapter implements CacheProtocol
│   │   ├── consumer/
│   │   │   ├── batch_processor.py   # getmany() batch loop (async)
│   │   │   ├── dedup.py             # Valkey SET idempotency (via CacheProtocol)
│   │   │   └── balance_writer.py    # INCRBY + async Postgres flush (via protocols)
│   │   ├── screener/
│   │   │   ├── rules.py             # Rule-based pre-screener (FR-60)
│   │   │   └── publisher.py         # Publish to cdr.fraud.flagged (aiokafka)
│   │   ├── dlq/
│   │   │   └── handler.py           # DLQ publish on failure (async)
│   │   └── management/
│   │       └── api.py               # FastAPI management plane (async, pause/resume/DLQ inspect)
│   ├── tests/
│   └── Dockerfile
│
├── app-backend/                     # All other backend (FastAPI monorepo for MVP)
│   ├── pyproject.toml               # psycopg[async,pool], valkey[asyncio], aiokafka, pymilvus, copilotkit, pydantic-settings
│   ├── src/
│   │   ├── main.py                  # FastAPI app entrypoint + middleware registration
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings Settings singleton (eager load)
│   │   │   ├── middleware.py        # OTEL trace middleware (extract traceparent → generate if absent)
│   │   │   ├── auth.py              # JWT decode + role guard (async)
│   │   │   └── protocols/           # Abstract interfaces (Dependency Inversion)
│   │   │       ├── db.py            # DatabaseProtocol: async execute / fetch / fetchrow / transaction
│   │   │       ├── vector_store.py  # VectorStoreProtocol: async search / upsert / delete
│   │   │       ├── cache.py         # CacheProtocol: async get / set / incrby / expire / delete
│   │   │       └── llm.py           # LLMClientProtocol: async complete / embed
│   │   ├── adapters/                # Concrete implementations of protocols
│   │   │   ├── postgres.py          # Psycopg3AsyncAdapter implements DatabaseProtocol (AsyncConnectionPool)
│   │   │   ├── milvus.py            # MilvusAdapter implements VectorStoreProtocol
│   │   │   ├── redis.py             # RedisAdapter implements CacheProtocol
│   │   │   └── azure_openai.py      # AzureOpenAIAdapter implements LLMClientProtocol
│   │   ├── routers/
│   │   │   ├── account.py           # FR-1–7 (async def routes)
│   │   │   ├── balance.py           # FR-8–11
│   │   │   ├── recharge.py          # FR-12–17
│   │   │   ├── notifications.py     # FR-18–21 (simulated delivery)
│   │   │   ├── chatbot.py           # FR-22–36 (CopilotKit runtime + LangGraph)
│   │   │   ├── ussd.py              # FR-37–41
│   │   │   ├── ops.py               # FR-42–52
│   │   │   ├── fraud.py             # FR-53–56 (case queue + agent)
│   │   │   ├── simulator.py         # FR-68–70
│   │   │   └── health.py            # FR-77 /health + /ready
│   │   ├── agents/
│   │   │   ├── chatbot/
│   │   │   │   ├── graph.py         # LangGraph state graph + CopilotKitState mixin
│   │   │   │   ├── support_agent.py
│   │   │   │   ├── rating_agent.py
│   │   │   │   ├── balance_agent.py
│   │   │   │   ├── conclusion_agent.py
│   │   │   │   ├── notification_agent.py
│   │   │   │   └── tools/
│   │   │   │       ├── rag_search.py      # Milvus hybrid search (via VectorStoreProtocol)
│   │   │   │       ├── plan_recommend.py  # Hybrid search + usage signals
│   │   │   │       └── ticket_create.py
│   │   │   ├── fraud/
│   │   │   │   ├── graph.py
│   │   │   │   └── fraud_agent.py
│   │   │   ├── ops/
│   │   │   │   ├── rule_induction_agent.py
│   │   │   │   ├── upsell_strategy_agent.py
│   │   │   │   └── rca_agent.py           # FR-75
│   │   │   └── shared/
│   │   │       ├── langfuse_client.py     # LangFuse tracing wrapper
│   │   │       └── embeddings.py          # text-embedding-3-small (via LLMClientProtocol)
│   │   ├── rag/
│   │   │   ├── bm25_index.py
│   │   │   ├── rrf_reranker.py
│   │   │   └── ingestion/
│   │   │       ├── faq_ingestor.py
│   │   │       ├── plan_ingestor.py
│   │   │       └── sop_ingestor.py
│   │   ├── ml/
│   │   │   ├── forecasting/
│   │   │   │   ├── subscriber_growth.py   # FR-44 scikit-learn
│   │   │   │   └── plan_demand.py         # FR-45 scikit-learn
│   │   │   └── evaluation/
│   │   │       ├── llm_judge.py           # FR-73
│   │   │       └── deepeval_runner.py     # FR-74
│   │   ├── models/                        # Pydantic schemas (shared)
│   │   │   ├── subscriber.py
│   │   │   ├── billing.py
│   │   │   ├── plan.py
│   │   │   └── fraud.py
│   │   └── db/
│   │       ├── migrations/                # Flyway SQL migrations (versioned)
│   │       │   ├── V1__baseline_schema.sql         # all tables + indexes + FK constraints
│   │       │   ├── V2__modified_at_trigger.sql     # trigger function + application to all tables
│   │       │   ├── V3__segmentation_kpi_mvw.sql    # segmentation_subscriber_kpi_r_mvw + refresh fn
│   │       │   ├── V4__billing_views.sql            # billing_usage_summary_i_vw
│   │       │   └── V5__grants.sql                   # app role grants (audit insert-only, etc.)
│   │       ├── identity/
│   │       │   ├── queries.py             # SELECT only — raw SQL via psycopg3
│   │       │   └── commands.py            # INSERT/UPDATE/DELETE — raw SQL via psycopg3
│   │       ├── billing/
│   │       │   ├── queries.py             # SELECT — billing_wallet_balances, billing_cdr_events, ...
│   │       │   └── commands.py            # INSERT — billing_transactions, billing_audit_log, ...
│   │       ├── fraud/
│   │       │   ├── queries.py
│   │       │   └── commands.py
│   │       ├── recharge/
│   │       │   ├── queries.py
│   │       │   └── commands.py
│   │       ├── support/
│   │       │   ├── queries.py
│   │       │   └── commands.py
│   │       └── seed/
│   │           ├── synthetic_generator.py # FR-71: 300K subs, 5M CDRs
│   │           └── sop_generator.py       # SOP knowledge base seed
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py                    # testcontainers: Postgres, Valkey, Redpanda
│   └── Dockerfile
│
├── frontend/                              # React 18 + Vite + TailwindCSS
│   ├── package.json                       # @copilotkit/react-ui, @copilotkit/react-core included
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                        # Role-based router root; <CopilotKit> wraps subscriber portal
│   │   ├── router.tsx                     # React Router v6 routes
│   │   ├── portals/
│   │   │   ├── subscriber/               # /subscriber/* (FR-1–36)
│   │   │   │   ├── Dashboard.tsx
│   │   │   │   ├── Balance.tsx
│   │   │   │   ├── Recharge.tsx
│   │   │   │   ├── Chatbot.tsx            # <CopilotChat> component; AG-UI stream
│   │   │   │   └── Profile.tsx
│   │   │   ├── ops/                       # /ops/* (FR-42–52)
│   │   │   │   ├── PlanStock.tsx
│   │   │   │   ├── OrderFulfilment.tsx
│   │   │   │   ├── Forecasts.tsx
│   │   │   │   └── Segmentation.tsx
│   │   │   ├── fraud/                     # /fraud/* (FR-53–56)
│   │   │   │   ├── AnomalyFeed.tsx
│   │   │   │   └── CaseQueue.tsx
│   │   │   └── simulator/                 # /simulator/* (FR-68–70)
│   │   │       ├── CdrSimulator.tsx
│   │   │       ├── NotificationPortal.tsx
│   │   │       └── SimActivation.tsx
│   │   ├── components/
│   │   │   ├── ui/                        # Shared: Button, Card, Badge, Table, Modal
│   │   │   ├── charts/                    # Recharts wrappers for time-series
│   │   │   └── layout/                    # Navbar, Sidebar, RoleGuard
│   │   ├── hooks/
│   │   │   ├── useBalance.ts
│   │   │   ├── useWebSocket.ts
│   │   │   └── useAuth.ts
│   │   ├── lib/
│   │   │   ├── api.ts                     # Axios instance + error interceptor
│   │   │   ├── auth.ts                    # JWT decode, role extraction
│   │   │   └── queryClient.ts             # TanStack Query client
│   │   └── types/
│   │       ├── subscriber.ts
│   │       ├── billing.ts
│   │       └── fraud.ts
│   ├── tests/                             # Vitest + React Testing Library
│   └── Dockerfile
│
├── docs/
│   ├── decision_logs/
│   │   └── Event Stream and CDR Pipeline.md
│   └── bmad_output/
│       └── planning-artifacts/
│           ├── prds/
│           └── architecture.md            # ← this document
│
└── scripts/
    ├── seed_db.sh
    ├── seed_milvus.sh
    └── generate_synthetic_data.py         # FR-71
```

**OTEL trace middleware (FastAPI):**

```python
# core/middleware.py
from opentelemetry import trace
from opentelemetry.propagate import extract
from starlette.middleware.base import BaseHTTPMiddleware

class OtelTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Extract traceparent from incoming headers; generate new span if absent
        ctx = extract(dict(request.headers))
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("http_request", context=ctx) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
```

**justfile commands (cross-platform):**

```just
# justfile — works on Windows (PowerShell), macOS, Linux
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

deps:         docker compose -f docker/docker-compose-dependencies.yaml up -d
up:           docker compose -f docker/docker-compose.yaml up -d
down:         docker compose -f docker/docker-compose.yaml down
logs:         docker compose -f docker/docker-compose.yaml logs -f
restart svc:  docker compose -f docker/docker-compose.yaml restart {{svc}}

backend:      cd app-backend && uvicorn src.main:app --reload --port 8000
frontend:     cd frontend && npm run dev
cdr:          cd cdr-pipeline && python -m src.main

migrate:      flyway -url=jdbc:postgresql://localhost:5432/sboai -locations=filesystem:app-backend/db/migrations migrate
seed:         cd app-backend && python scripts/generate_synthetic_data.py
seed-milvus:  cd app-backend && python scripts/seed_milvus.sh

test:         cd app-backend && pytest tests/ -v
test-cdr:     cd cdr-pipeline && pytest tests/ -v
test-fe:      cd frontend && npm run test

lint:         cd app-backend && ruff check src/ && cd ../cdr-pipeline && ruff check src/
format:       cd app-backend && ruff format src/ && cd ../cdr-pipeline && ruff format src/
lint-fe:      cd frontend && npm run lint
```

### 1.12.2. Docker Compose Services (MVP)

**Two-file Docker Compose split:** Infrastructure dependencies are defined in `docker/docker-compose-dependencies.yaml`. The full stack `docker/docker-compose.yaml` uses Compose's `include:` directive to reuse all dependency definitions and adds the application services on top. This allows local development with just `docker compose -f docker/docker-compose-dependencies.yaml up -d` — no codebase containers needed while iterating.

**MiniStack** MiniStack is lighter, faster to start, and sufficient for the Cognito + S3 surface area used in MVP.

**Valkey (standalone, not MiniStack-bundled):** Valkey runs as its own dedicated container, independent of MiniStack. This avoids any implicit dependency on MiniStack's internal Redis and gives a clean separation: Valkey = application data layer; MiniStack = Cognito/S3 simulation.

**Persistence:** Named Docker volumes are configured for Cognito user pools, S3 objects, and PostgreSQL data so state survives container restarts during development.

**`docker/docker-compose-dependencies.yaml` — infrastructure only:**

```yaml
services:
  redpanda:          # Kafka-compatible event bus
  valkey:            # Balance buffer, session, dedup, OTP (standalone; maxmemory-policy noeviction)
    volumes:
      - valkey_data:/data
  postgres:          # Primary DB
    volumes:
      - postgres_data:/var/lib/postgresql/data   # persisted across restarts

  milvus:            # Vector store (+ etcd + minio as deps)
  langfuse:          # Agent observability
  ministack:         # AWS Cognito + S3 simulation (no Redis bundled — Valkey is separate)
    volumes:
      - ministack_cognito:/var/lib/ministack/cognito   # user pools + app clients persisted
      - ministack_s3:/var/lib/ministack/s3             # S3 buckets + objects persisted

  otel-collector:    # OTEL collector
  otel-tui:          # Terminal traces/metrics/logs viewer
  fluentd:           # Log routing

volumes:
  postgres_data:
  valkey_data:
  ministack_cognito:
  ministack_s3:
```

**`docker/docker-compose.yaml` — full stack (extends dependencies):**

```yaml
include:
  - docker-compose-dependencies.yaml   # reuse all infra service definitions

services:
  cdr-pipeline:      # CDR consumer + management API
  app-backend:       # FastAPI monorepo
  frontend:          # Vite dev server (or nginx for built assets)
```

**Non-persisted services (acceptable to reset on restart):** Valkey, Redpanda, Milvus, LangFuse. Valkey balance state cold-starts from Postgres; Redpanda offset reset is safe during dev; Milvus collections are re-seeded via `just seed-milvus`.

---

## 1.13. Architecture Validation

### 1.13.1. Decision Compatibility ✅

- Redpanda (Kafka-wire-compatible) → aiokafka consumer works unchanged
- Valkey (Docker, standalone) → Redis-compatible; Python `valkey[asyncio]` client; same wire protocol as Redis
- LangGraph + Azure OpenAI: supported; `langchain-openai` with Azure base URL
- OTEL-TUI + OTEL Collector: standard OTLP receiver
- Milvus: `pymilvus` client; HNSW + BM25 hybrid supported in Milvus 2.4+
- WeasyPrint: pure Python; no browser dep; works in Docker Alpine

### 1.13.2. NFR Coverage ✅

| NFR                           | Architecture Support                                                      |
| ----------------------------- | ------------------------------------------------------------------------- |
| P95 ≤ 200ms balance deduction | Valkey/Redis INCRBY; Postgres async flush; agents off hot path            |
| 100K eps (Target)             | Rust consumer + MSK 24 partitions + Valkey                                |
| Idempotency                   | Valkey SET dedup + recharge idempotency key + notification once-per-event |
| TRAI data localisation        | All AWS in `ap-south-1`; no cross-region                                  |
| 6-year audit retention        | Postgres append-only + S3 archive                                         |
| PCI-DSS                       | Tokenisation at entry; raw PAN never persisted                            |
| PII encryption                | pgcrypto AES-256 + Fluentd redaction                                      |
| FR-36 rate limiting           | MVP: not enforced; Target State: API Gateway per-subscriber throttle      |
| FR-66 account takeover        | Postgres `fraud_blacklist` + Cognito account disable + token revocation → API Gateway JWT validation blocks all subsequent calls |
| FR-77 health checks           | `/health` + `/ready` on every FastAPI service                             |

### 1.13.3. FR Coverage ✅

All 77 FRs are architecturally addressed:

- FR-1–7 (Account & Identity): `account` router + Cognito/Keycloak + `identity` schema
- FR-8–11 (Balance & Usage): `balance` router + Valkey hot read + Postgres
- FR-12–17 (Recharge): `recharge` router + idempotency key + WeasyPrint receipts
- FR-18–21 (Notifications): threshold checks in CDR pipeline consumer + `notification.events` topic
- FR-22–36 (Chatbot): LangGraph graph + Milvus RAG + A2A nodes + LangFuse
- FR-37–41 (USSD): `ussd` router + Valkey session per `session_id`
- FR-42–52 (Ops Dashboard): `ops` router + materialised KPI view + scikit-learn + LangGraph segmentation agents
- FR-53–56 (Fraud Dashboard): `fraud` router + WebSocket push + `fraud.alerts` topic
- FR-57–59 (CDR Pipeline): Redpanda + aiokafka + Valkey + Postgres + DLQ
- FR-60–62 (Fraud Agent): rule screener + LangGraph Fraud Agent + `fraud_cases` table
- FR-63–67 (Security): pgcrypto + TLS + Fluentd redaction + Postgres/Cognito blacklist + JWT roles
- FR-68–70 (Simulator): `simulator` router + WebSocket trace stream + MiniStack
- FR-71 (Synthetic Dataset): `synthetic_generator.py` — 300K subs, 5M CDRs, 1K plans
- FR-72–77 (Eval/Obs): LangFuse + OTEL + DeepEval + LLM-as-Judge + `/health`+`/ready`

### 1.13.4. Gap Analysis

**Critical Gaps:** None.

**Important Notes (not gaps — implementation decisions):**

- Target State ML forecasting model (TimesFM/Chronos/Prophet) — deferred post-MVP by design
- Keycloak Realm configuration detail — implementation-time decision
- Milvus collection schema exact field types — implementation-time; architecture defines domains

**Deferred to Production (by PRD):**

- Real payment gateway integration
- Real SMS/push gateway (Twilio, MSG91)
- Consent management
- Session timeout / token revocation
- ML fraud classifier (architecture hook only)

### 1.13.5. Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed (Enterprise; MVP 10K eps, Target 100K eps)
- [x] Technical constraints identified (200ms SLA, India data localisation, Milvus fixed, Postgres fixed)
- [x] Cross-cutting concerns mapped (trace ID, idempotency, async agents, PII)

**Architectural Decisions**

- [x] Critical decisions documented with versions (all stack components specified)
- [x] Technology stack fully specified (MVP and Target State separately)
- [x] Integration patterns defined (Kafka topics, REST boundaries, A2A via LangGraph)
- [x] Performance considerations addressed (Valkey write buffer, Rust target, async agent path)

**Implementation Patterns**

- [x] Naming conventions established (DB, API, Python, Kafka, React)
- [x] Structure patterns defined (two-codebase MVP; microservices Target)
- [x] Communication patterns specified (Kafka envelopes, REST envelope, WebSocket for real-time)
- [x] Process patterns documented (error handling, PII hygiene, testing, DLQ)

**Project Structure**

- [x] Complete directory structure defined
- [x] Component boundaries established (cdr-pipeline vs app-backend; FR mapping to routers/agents)
- [x] Integration points mapped (Kafka topics, Valkey key patterns, Milvus collections)
- [x] Requirements to structure mapping complete

### 1.13.6. Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**

- Balance hot path is fully isolated from agent execution — 200ms SLA is structurally enforced
- Two-codebase MVP structure minimises inter-service complexity while keeping Target State migration clean
- Decision log (`Event Stream and CDR Pipeline.md`) pre-resolved the hardest pipeline decisions
- Milvus hybrid search (dense + BM25 + RRF) is a well-understood pattern; pymilvus 2.4+ supports it natively
- Fluentd as the single log routing layer means MVP→Target observability switch is a config change, not a code change

**Areas for Future Enhancement (post-MVP):**

- Rust CDR pipeline build and testing pipeline (GitHub Actions Rust workflow)
- Keycloak realm export/import for reproducible Target State auth config
- Deep learning forecasting model evaluation (TimesFM vs Chronos vs Prophet benchmarks on synthetic data)
- Milvus collection schema versioning strategy as knowledge base grows

### 1.13.7. Implementation Handoff

**AI Agent Guidelines:**

- The two-codebase boundary (`cdr-pipeline/` vs `app-backend/`) is hard — no HTTP calls across it in MVP
- All agents must be async (never `await` an LLM call inside the Kafka batch processing loop)
- Every FastAPI endpoint must emit OTEL spans with `trace_id`; LangGraph nodes must pass `trace_id` in LangFuse metadata
- PII never in log statements — use subscriber UUID or MSISDN suffix `[-4:]`
- All Kafka messages must include `traceparent` in headers AND `trace_id` in JSON body

**First Implementation Priorities:**

1. `docker-compose.yml` — bring up all infra (Redpanda, Redis, Postgres, Milvus, MiniStack, LangFuse, OTEL-TUI, Fluentd)
2. Postgres schema migrations (Flyway SQL) — all domains, views, triggers
3. Synthetic dataset generation (`scripts/generate_synthetic_data.py`) — 300K subs, 5M CDRs
4. CDR pipeline consumer (`cdr-pipeline/`) — dedup + balance write + fan-out
5. Core FastAPI app (`app-backend/`) — account, balance, recharge routers
6. LangGraph chatbot graph — Support Agent + RAG tool + Milvus ingest
7. Frontend shell — React Router + role-based layout + auth integration
