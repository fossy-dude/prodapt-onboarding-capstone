---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - docs/bmad_output/planning-artifacts/prds/prd-sboai_capstone-2026-06-18/prd.md
  - docs/bmad_output/planning-artifacts/architecture.md
---

# AI-Powered Prepaid Billing System - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for the AI-Powered Prepaid Billing System, decomposing requirements from the PRD (77 FRs) and Architecture into implementable stories for the Developer agent. Stories are sized at 1–2 days of dev work, sequenced by build-order dependency, and organized into 7 user-value epics.

No UX design document exists; UX briefs are generated as story-driven deliverables within each portal epic, derived from PRD user journeys (UJ-1 through UJ-5).

---

## Requirements Inventory

### Functional Requirements

FR-1: A new subscriber can submit an online sign-up form and receive a unique Subscriber Registration ID before SIM activation.
FR-2: A subscriber can track their SIM activation progress through a step-by-step UI journey simulating the order fulfilment lifecycle (Created → KYC → Activated).
FR-3: A subscriber can submit the TRAI Customer Acquisition Form digitally as part of the SIM activation flow, with an immutable audit trail.
FR-4: A subscriber can log in using Subscriber Registration ID (pre-activation) or MSISDN + credentials (post-activation), with step-up OTP enforcement.
FR-5: An authenticated subscriber can view and edit personal details, saved addresses, and KYC status.
FR-6: An authenticated subscriber can store and manage payment methods: credit card (tokenised), UPI ID, net banking, and mobile wallet details.
FR-7: A subscriber can see their current KYC state (verified | pending | rejected) at any time from their profile.
FR-8: An authenticated subscriber can view their current prepaid Wallet Balance in INR, updated after every CDR deduction.
FR-9: An authenticated subscriber can view a full ledger of charges, recharges, and refunds with timestamp and CDR reference.
FR-10: An authenticated subscriber can view per-type consumption for the current plan period: voice (minutes), data (MB/GB), SMS (count), and roaming.
FR-11: An authenticated subscriber can view their active plan name, validity expiry date, bundled quotas, and remaining allowances.
FR-12: An authenticated subscriber can browse all active prepaid plans with data/voice/SMS bundles, validity, and pricing.
FR-13: An authenticated subscriber can select a plan, pay via a saved or new payment method, and activate the plan on their account.
FR-14: The system accepts payment method selection across credit card, net banking, UPI, and mobile wallets. All payments are simulated for MVP.
FR-15: A subscriber receives a downloadable PDF receipt for each completed recharge transaction.
FR-16: The system prevents double-charging when a recharge is retried due to network failure or client retry.
FR-17: A subscriber can view a list of failed recharge transactions. Actual refund processing is not implemented in MVP.
FR-18: The system sends a simulated SMS and push notification when a subscriber's Wallet Balance drops below ₹10 (threshold stored in DB config record).
FR-19: The system sends a simulated SMS and push notification when a subscriber's Wallet Balance reaches zero or near-zero.
FR-20: The system sends a simulated SMS and push notification 3 days before a subscriber's active plan expires (lead-time stored in DB config record).
FR-21: The system sends a simulated SMS notification when a subscriber's data allowance drops below 10% remaining.
FR-22: A subscriber can query their current Wallet Balance and remaining quota via the chatbot.
FR-23: A subscriber can ask about their active plan, expiry date, and feature details via the chatbot.
FR-24: A subscriber can initiate and complete a recharge workflow through the chatbot via tool-calling to the payment flow.
FR-25: The chatbot maintains conversational context across all turns within a single session.
FR-26: The chatbot answers general telecom FAQs and plan/billing queries by retrieving from a structured knowledge base (RAG).
FR-27: The chatbot rejects malformed, adversarial, or suspicious inputs before processing.
FR-28: An authenticated subscriber can view their previously raised support tickets via the chatbot.
FR-29: The Support Agent queries the Rating Agent to explain the charge breakdown for a specific CDR event.
FR-30: A subscriber can raise a billing dispute via the chatbot, which auto-creates a support ticket with pre-filled details and provides the ticket ID.
FR-31: The Support Agent queries the Balance Management Agent for wallet-related queries, via A2A protocol.
FR-32: The Support Agent offers a plan recommendation using a hybrid search combining plan attribute matching, semantic retrieval, and subscriber usage signals.
FR-33: When a subscriber explicitly selects a recommended plan, the system logs the acceptance with a handoff message. Dismissals are also logged.
FR-34: At the end of each chatbot session, the Conclusion Agent stores interaction learnings and triggers the Notification Agent with a conversation summary.
FR-35: The Notification Agent, upon receiving a conversation summary from the Conclusion Agent, decides whether, when, and how to send a notification.
FR-36: The system enforces a limit of 100 requests per minute (RPM) per subscriber across API, USSD, and chatbot channels (configurable via DB record).
FR-37: The system receives USSD REST API callbacks from the telecom operator and responds with structured text menus.
FR-38: A subscriber can check their current Wallet Balance via a USSD menu option.
FR-39: A subscriber can view their active plan details via a USSD menu option.
FR-40: A subscriber can initiate a recharge workflow through the USSD menu.
FR-41: A subscriber can manage notification alert preferences via a USSD menu option.
FR-42: An operations team member can view real-time subscriber counts per active plan.
FR-43: An operations team member can view a live view of subscriber orders across all fulfilment states.
FR-44: The system provides a 3-month projection of subscriber activations and churn using a time-series ML model.
FR-45: The system provides demand forecasting per plan for marketing targeting (30–90 days).
FR-46: A marketing team member can define a subscriber candidate pool by applying composable filter criteria on KPIs sourced from a materialised database view.
FR-47: The system shows a sample subscriber table and pool-level statistics for the filtered candidate pool.
FR-48: The system sends pre-aggregated feature vectors for up to 100 sampled subscribers to an LLM for descriptive segment label assignment.
FR-49: A Rule Induction Agent generalises per-customer LLM labels into interpretable KPI-predicate segment rules, persisted to the database.
FR-50: The system applies saved segment rules to classify the full filtered subscriber base deterministically, with per-segment statistics.
FR-51: An LLM agent generates a textual upsell strategy per identified subscriber segment.
FR-52: An operations team member can monitor CDR processing health, charging pipeline latency, and notification delivery status.
FR-53: A fraud analyst can view a live feed of CDR events flagged by the rule-based pre-screening layer.
FR-54: Confirmed risk cases escalated by the Fraud Detection Agent appear in a case queue for fraud supervisors.
FR-55: The system detects SIM swap account takeover patterns and surfaces dedicated alerts.
FR-56: The system flags abnormal recharge frequency or amounts and surfaces alerts.
FR-57: The system ingests CDR events from the telecom operator's upstream pipeline in real time, with dead-letter capture for failed events.
FR-58: The system deducts the appropriate charge from the subscriber's Wallet Balance on each CDR receipt, deterministically and idempotently (P95 ≤ 200ms).
FR-59: Every billing, authentication, and administrative action is recorded in an immutable audit log (6-year retention per TRAI).
FR-60: Every ingested CDR event is evaluated against a rule set for anomaly signals before being passed to the Fraud Detection Agent.
FR-61: Flagged CDR events are routed to the Fraud Detection Agent for LLM-powered deeper risk analysis.
FR-62: The Fraud Detection Agent triggers a notification to the fraud supervisor when risk is confirmed.
FR-63: All Personally Identifiable Information is encrypted at rest and in transit.
FR-64: Card payment data is tokenised; raw card numbers are never stored or transmitted through the system.
FR-65: The system adheres to TRAI regulations for billing, data handling, and subscriber data localisation.
FR-66: The system implements authentication hardening and integrates SIM swap detection with the login flow. On confirmed SIM swap risk, account is blacklisted, disabled at API gateway, and active JWTs are revoked.
FR-67: All four dashboards use JWT-based auth with role separation.
FR-68: A developer/admin can generate synthetic CDR events and observe end-to-end trace logs across each service in real time.
FR-69: All simulated notifications sent to subscribers (SMS, push, OTP) are surfaced on a live Notification Portal for observation.
FR-70: An operator/admin can simulate the SIM card activation flow and progress a subscriber's order to Activated status.
FR-71: The system includes scripts to generate a synthetic dataset: ≥1,000 plans, 300,000 subscribers, and 5,000,000 CDRs.
FR-72: All multi-agent workflows are instrumented with LangFuse for end-to-end trace visibility.
FR-73: An LLM-as-Judge mechanism validates plan recommendation relevance and chatbot response quality.
FR-74: DeepEval is integrated for chatbot quality metrics and prediction accuracy evaluation.
FR-75: An LLM-powered Root Cause Analysis Agent assists engineering teams in diagnosing billing discrepancies and failed recharges.
FR-76: A trace ID is propagated across the full CDR → balance → fraud → notification pipeline for end-to-end observability.
FR-77: Every microservice exposes /health and /ready endpoints.

---

### NonFunctional Requirements

NFR-1: Balance deduction P95 latency ≤ 200ms from CDR receipt.
NFR-2: CDR ingestion pipeline must be architecturally capable of 100,000 events/second (Target State). MVP targets ~10,000 eps for functional correctness.
NFR-3: All subscriber data must be physically stored within India borders (TRAI data localisation mandate).
NFR-4: Billing records must be retained for a minimum of 6 years per TRAI mandate.
NFR-5: Card payment data must never be stored as raw PAN; tokenisation required at point of entry (PCI-DSS).
NFR-6: PII (MSISDN, name, address, financial data) must be encrypted at rest using AES-256 or equivalent.
NFR-7: All API communication must use TLS 1.2+.
NFR-8: LLM discovery sample for upsell segmentation is hard-capped at 100 subscribers per session for token cost control.
NFR-9: Balance deduction idempotency — each CDR reference ID must result in exactly one deduction; duplicates are silently discarded.
NFR-10: Chatbot containment rate target ≥ 70% at launch (subscriber queries resolved without human escalation).
NFR-11: Chatbot response quality (LLM-as-Judge) ≥ 80% pass rate on relevance and accuracy rubric.
NFR-12: Chatbot hallucination rate (DeepEval) < 5%.
NFR-13: Fraud detection escalation accuracy ≥ 75% true positive rate (agent-confirmed vs. supervisor-cleared).
NFR-14: Subscriber growth forecast MAPE < 15% on 3-month activation/churn projection.
NFR-15: CDR simulator trace completeness — 100% of simulated events must show full end-to-end trace.
NFR-16: PII must never appear in logs or OTEL span attributes — use subscriber UUID or MSISDN suffix [-4:] only.
NFR-17: Every Kafka message must include traceparent in headers AND trace_id in JSON body.
NFR-18: The two-codebase boundary (cdr-pipeline/ vs service_backend/) is hard — no HTTP calls between them in MVP; communication only via shared Postgres and Redis/Valkey.
NFR-19: Health check endpoints (/health, /ready) must respond within 200ms under normal operating conditions.
NFR-20: Rate limit threshold is configurable via a database configuration record (not hardcoded) — default 100 RPM per subscriber per channel.

---

### Additional Requirements

From Architecture document — technical requirements that impact epic and story creation:

ARCH-1: Two-codebase structure: cdr-pipeline/ (Python + aiokafka) and service_backend/ (Python + FastAPI). No inter-service HTTP calls in MVP; they share Postgres and Valkey.
ARCH-2: Postgres container init scripts (docker/postgres/init/01_extensions.sql, 02_roles.sql, 03_databases.sql) must run at container creation time. Extensions: pg_uuidv7, pgcrypto, pg_trgm, btree_gin.
ARCH-3: Flyway SQL-native migrations (V1__baseline_schema.sql through V5__grants.sql). No ORM DDL. No ad-hoc schema changes outside migrations.
ARCH-4: All database queries use raw SQL via psycopg3 async. CQRS split: queries.py (SELECT only) and commands.py (INSERT/UPDATE/DELETE only) per domain.
ARCH-5: Valkey key domains: dedup:{cdr_id} (24h TTL), balance:{msisdn} (no TTL — noeviction policy required), session:{session_id} (30m HASH), otp:{msisdn} (5m), chat_context:{session_id} (2h HASH).
ARCH-6: balance:{msisdn} key must never be evicted. Valkey maxmemory-policy must be set to noeviction. On cdr-pipeline restart, load_balances_from_postgres() re-seeds all balance keys before the consumer loop starts.
ARCH-7: Milvus Lite runs embedded in-process (pymilvus[milvus-lite]) in service_backend. No separate container. Data persisted to Podman volume milvus_lite_data mounted at /app/data/milvus/sboai.db.
ARCH-8: Three Milvus collections: faq_chunks (category, source_doc, plan_type metadata), plan_vectors (plan_id, plan_type, price, validity), sop_chunks (rule_id, severity, domain). All use text-embedding-3-small (1536 dims), HNSW index, BM25 + RRF for hybrid search.
ARCH-9: UUID strategy — UUIDv7 (uuid_generate_v7()) for all transactional/high-insert tables; UUIDv4 (gen_random_uuid()) for reference/config tables. Python-side: use uuid7 package.
ARCH-10: Kafka topics: cdr.raw (24 partitions, key=subscriber_id), cdr.enriched.filtered (24p), cdr.fraud.flagged (6p), fraud.alerts (6p), notification.events (12p), cdr.dlq (6p).
ARCH-11: Kafka event envelope: {event_type, event_id, trace_id, timestamp, payload}. traceparent in Kafka header AND trace_id in JSON body.
ARCH-12: All FastAPI responses use standard envelope: success={data, meta:{trace_id, timestamp}}, error={error:{code, message, detail}, meta}.
ARCH-13: LangGraph + CopilotKit AG-UI protocol for chatbot. CopilotKit runtime wired as FastAPI router at POST /api/chat/stream.
ARCH-14: Fraud Detection Agent runs asynchronously — never in the balance deduction hot path. Agent analysis starts after CDR deduction completes and cdr.enriched.filtered is published.
ARCH-15: All FastAPI routes are async def. All I/O libraries are async: psycopg3 AsyncConnectionPool, valkey[asyncio], aiokafka, pymilvus async.
ARCH-16: Dependency Inversion: all I/O adapters implement typed Protocol interfaces in core/protocols/. Business logic depends only on protocols, never on concrete libraries.
ARCH-17: pydantic-settings singleton per service, loaded once at module import. .env.example committed; .env gitignored. Fails fast on missing required values.
ARCH-18: justfile as cross-platform task runner (works on Windows/macOS/Linux). Key commands: just deps, just up, just migrate, just seed, just seed-milvus, just test, just lint.
ARCH-19: GitHub Actions CI runs uv tox (lint + typecheck + test) on every PR. All three must pass before merge.
ARCH-20: Linting: ruff (lint + format) + pyrefly (static type checking). Frontend: Vitest + ESLint + TypeScript strict mode.
ARCH-21: WebSocket for real-time UI: fraud anomaly feed (fraud.alerts consumer), Notification Portal (notification.events consumer), CDR Simulator trace stream.
ARCH-22: React Query (TanStack Query) for server state. No global state library. Local component state for UI interactions.
ARCH-23: CopilotKit frontend: @copilotkit/react-ui + @copilotkit/react-core. <CopilotKit runtimeUrl="/api/chat/stream"> wraps subscriber portal. useCopilotReadable hooks expose balance, plan, session context to agent.
ARCH-24: Synthetic data generation order is critical: 1. Plans (1K, UUIDv4) via V5__seed_plans.sql Flyway migration → 2. Subscribers (300K, UUIDv4) → 3. CDRs (5M, UUIDv7). Each layer references the previous. CDR generation uses psycopg3 COPY protocol in batches of 50K.
ARCH-25: Fraud signals embedded in ~0.5% of subscribers: unusual CDR velocity, SIM swap flags. Required for fraud agent testing.
ARCH-26: SOP knowledge base (sop_rules, sop_knowledge_chunks tables) seeded via sop_generator.py. Same predefined SOP rules used to build KB must also be used to generate synthetic CDR records with embedded internal notes for agent validation.
ARCH-27: OTEL trace middleware in FastAPI extracts traceparent from incoming headers; generates new span if absent. trace_id stored in request.state.trace_id and returned in X-Trace-Id response header.
ARCH-28: Podman Compose two-file split: docker-compose-dependencies.yaml (infra only) + docker-compose.yaml (full stack via include:). Allows running just infra without app containers during development.
ARCH-29: Postgres named volumes persist across restarts: postgres_data, ministack_cognito, ministack_s3, milvus_lite_data. Valkey and Redpanda are non-persisted — acceptable to reset.
ARCH-30: README.md at project root is the single authoritative onboarding document. Required sections: Prerequisites, MVP Setup (6 steps), Target State Setup (Terraform → migrate → seed → deploy).
ARCH-31: Terraform manages Target State infra (infrastructure/terraform/). MVP infrastructure is Podman Compose only — Terraform is not needed for local development.
ARCH-32: PII hygiene rules (ALL agents must follow): never log raw MSISDN/name/address/card data; use msisdn[-4:] suffix or [REDACTED]; never include PII in OTEL span attributes; use subscriber UUID only.
ARCH-33: Account takeover (FR-66): on confirmed SIM swap verdict → write to fraud_blacklist table → Cognito admin API disables account + revokes all tokens → API Gateway JWT validation blocks all subsequent calls. No Redis blacklist cache — Cognito is the enforcement layer.
ARCH-34: Valkey OTP key (otp:{msisdn}, 5m TTL) is for mid-session step-up verification only. Initial login OTP is handled by Cognito's Custom Auth Flow.

---

### UX Design Requirements

No UX design document exists for this project. UX requirements are derived from PRD User Journeys:

UX-DR1: Subscriber registration and pre-activation flow — multi-step form with Registration ID display and OTP entry screen (UJ-1). A lightweight UX brief story must define screen flows, component names, and key interactions before frontend stories in Epic 1.
UX-DR2: Post-activation self-care portal — balance dashboard, plan details card, usage breakdown by type, transaction history list, plan catalogue with filter/sort, recharge flow with payment method selection, PDF receipt download link (UJ-2). UX brief story required before Epic 3 frontend stories.
UX-DR3: Chatbot interface — CopilotChat embedded component with streaming AG-UI events; must handle tool-call visualisation (charge breakdown, plan recommendations), ticket creation confirmation, and session-end summary notification (UJ-3). UX brief story required before Epic 5 frontend stories.
UX-DR4: Fraud analyst dashboard — real-time anomaly feed (WebSocket-driven list), fraud case queue with status transitions and notes, SIM swap alert badges. Role-gated to fraud role JWT claim (UJ-4). Design derivable from FR-53–56 consequences.
UX-DR5: Ops/marketing dashboard — plan stock table, order fulfilment status grouped view, time-series forecast charts with confidence intervals, Target Base Builder filter UI with dynamic KPI columns from materialised view schema, pool preview table, segment labelling progress, upsell strategy text output (UJ-5). Design derivable from FR-42–52 consequences.
UX-DR6: Simulator dashboard — CDR parameter form, per-stage trace log display (WebSocket), Notification Portal live feed list, SIM activation admin button. Admin-only role gate.
UX-DR7: Role-based routing: /subscriber/* (subscriber role), /ops/* (ops role), /fraud/* (fraud role), /simulator/* (admin role). JWT role claim mismatch → redirect to login. Single SPA with TailwindCSS utility classes only.
UX-DR8: React component naming conventions: PascalCase.tsx for components, usePascalCase.ts for hooks. Shared components in components/ui/ (Button, Card, Badge, Table, Modal) and components/charts/ (Recharts wrappers for time-series).

---

### FR Coverage Map

FR-1: Epic 1 — Subscriber account registration, Registration ID generation
FR-2: Epic 1 — SIM activation order fulfilment (simulated UI flow)
FR-3: Epic 1 — TRAI CAF digital submission, immutable audit trail
FR-4: Epic 1 — Login/OTP (pre-activation Registration ID; post-activation MSISDN)
FR-5: Epic 1 — Profile management (name, address, contact details)
FR-6: Epic 1 — Saved payment methods management, PCI-DSS tokenisation
FR-7: Epic 1 — KYC status visibility (verified/pending/rejected)
FR-8: Epic 3 — Real-time balance display in INR
FR-9: Epic 3 — Transaction history (paginated ledger)
FR-10: Epic 3 — Usage breakdown by type
FR-11: Epic 3 — Plan details view
FR-12: Epic 3 — Plan catalogue browse
FR-13: Epic 3 — Recharge purchase
FR-14: Epic 3 — Multi-gateway payment (simulated)
FR-15: Epic 3 — PDF receipt generation
FR-16: Epic 3 — Idempotent recharge guard
FR-17: Epic 3 — Refund view (dummy failed transactions list)
FR-18: Epic 4 — Low balance alert notification
FR-19: Epic 4 — Balance depletion alert notification
FR-20: Epic 4 — Plan expiry reminder notification (3 days)
FR-21: Epic 4 — Contextual data top-up nudge notification
FR-22: Epic 5 — Balance inquiry via chatbot
FR-23: Epic 5 — Plan query via chatbot
FR-24: Epic 5 — Recharge assistance via chatbot
FR-25: Epic 5 — Multi-turn session memory
FR-26: Epic 5 — RAG FAQ assistant (Milvus hybrid search)
FR-27: Epic 5 — Input validation guardrails
FR-28: Epic 5 — Customer support ticket viewing via chatbot
FR-29: Epic 5 — Rating Agent (charge breakdown explanation)
FR-30: Epic 5 — Disputed transaction workflow (ticket auto-creation)
FR-31: Epic 5 — Balance Management Agent integration (A2A)
FR-32: Epic 5 — Plan recommendation tool (hybrid search + usage signals)
FR-33: Epic 5 — Recommendation feedback loop (acceptance/dismissal logging)
FR-34: Epic 5 — Conclusion Agent (session learning + Notification Agent trigger)
FR-35: Epic 5 — Notification Agent (A2A session-end notification decision)
FR-36: Epic 4 (USSD channel) + Epic 5 (chatbot channel) — Rate limiting 100 RPM
FR-37: Epic 4 — USSD session callback handling
FR-38: Epic 4 — Balance check via USSD
FR-39: Epic 4 — Plan info via USSD
FR-40: Epic 4 — Recharge initiation via USSD
FR-41: Epic 4 — Notification opt-in/out via USSD
FR-42: Epic 7 — Plan stock dashboard
FR-43: Epic 7 — Order fulfilment status view
FR-44: Epic 7 — Subscriber growth forecast (ML, 3-month)
FR-45: Epic 7 — Plan popularity forecast (30–90 day)
FR-46: Epic 7 — Target Base Builder (dynamic KPI filter on materialised view)
FR-47: Epic 7 — Pool preview and statistics
FR-48: Epic 7 — LLM per-customer segment labelling
FR-49: Epic 7 — Rule Induction Agent
FR-50: Epic 7 — Segment classification at scale (deterministic)
FR-51: Epic 7 — Upsell strategy recommendations
FR-52: Epic 7 — Ops dashboard observability (CDR monitor, pipeline health, notification delivery)
FR-53: Epic 6 — Real-time anomaly feed
FR-54: Epic 6 — Fraud case queue
FR-55: Epic 6 — SIM swap fraud alerts
FR-56: Epic 6 — Suspicious recharge pattern alerts
FR-57: Epic 2 — CDR ingestion pipeline (aiokafka consumer, dedup, DLQ)
FR-58: Epic 2 — Balance deduction engine (Valkey INCRBY + async Postgres flush)
FR-59: Epic 2 — Audit log trail (immutable, 6-year retention)
FR-60: Epic 6 — Rule-based pre-screening
FR-61: Epic 6 — Agent escalation on risk (Fraud Detection Agent, LangGraph async)
FR-62: Epic 6 — Fraud supervisor notification (confirmed risk)
FR-63: Epic 1 — PII encryption (pgcrypto AES-256, TLS 1.2+)
FR-64: Epic 1 — Payment data tokenisation (PCI-DSS)
FR-65: Epic 1 — TRAI compliance (data localisation, CAF audit trail, retention)
FR-66: Epic 6 — Account takeover prevention (blacklist + Cognito disable + JWT revocation)
FR-67: Epic 1 — JWT-based auth and role separation (4 dashboards)
FR-68: Epic 2 — CDR Simulator (UI + WebSocket trace display)
FR-69: Epic 2 — Notification Portal (live WebSocket feed)
FR-70: Epic 2 — SIM Activation Simulator (admin activate action)
FR-71: Epic 2 — Synthetic dataset generation (1K plans, 300K subscribers, 5M CDRs)
FR-72: Epic 1 (infra setup) + Epic 5 (chatbot traces) + Epic 6 (fraud traces) + Epic 7 (ops traces) — LangFuse agentic observability
FR-73: Epic 5 (chatbot eval harness) + Epic 7 (upsell quality rubric) — LLM-as-Judge evaluation
FR-74: Epic 5 — DeepEval integration (chatbot quality metrics)
FR-75: Epic 7 — Root Cause Analysis Agent
FR-76: Epic 2 — Distributed trace ID propagation (CDR → balance → fraud → notification)
FR-77: Epic 1 — Health check endpoints (/health, /ready) on every service

---

## Epic List

### Epic 1: Core Infrastructure, Tooling & Subscriber Identity
Subscribers can register, verify their identity, log in, manage their profile, and access the system securely. The full development infrastructure (Podman Compose, Postgres, Flyway, CI/CD, observability) is set up and operational. This epic is the prerequisite for all other epics.
**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-63, FR-64, FR-65, FR-67, FR-72 (LangFuse setup), FR-77

### Epic 2: CDR Pipeline, Balance Engine, Synthetic Data & Simulator Tools
The real-time CDR ingestion pipeline is operational, deterministically deducting balances and propagating events. A synthetic dataset is generated for all downstream testing. The simulator dashboard gives developers full visibility into the end-to-end pipeline.
**FRs covered:** FR-57, FR-58, FR-59, FR-68, FR-69, FR-70, FR-71, FR-76

### Epic 3: Subscriber Self-Care Portal
Subscribers can view their real-time balance and usage, browse plans, make recharges, download receipts, and view transaction history through the web portal.
**FRs covered:** FR-8, FR-9, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-17

### Epic 4: Notifications & USSD Interface
Subscribers receive proactive balance and plan alerts via simulated SMS/push. They can also self-serve via USSD (balance check, plan info, recharge initiation, notification preferences).
**FRs covered:** FR-18, FR-19, FR-20, FR-21, FR-36 (USSD + API channel), FR-37, FR-38, FR-39, FR-40, FR-41

### Epic 5: Self-Care Chatbot — Multi-Agent (TDD-first)
Subscribers can resolve billing queries, understand charges, raise disputes, get plan recommendations, and initiate recharges through an intelligent multi-agent chatbot with RAG, A2A communication, and full LangFuse observability.
**FRs covered:** FR-22, FR-23, FR-24, FR-25, FR-26, FR-27, FR-28, FR-29, FR-30, FR-31, FR-32, FR-33, FR-34, FR-35, FR-36 (chatbot channel), FR-72 (chatbot traces), FR-73, FR-74

### Epic 6: Fraud Detection (TDD-first)
The fraud management team can monitor real-time CDR anomalies, review AI-escalated fraud cases, and take action on SIM swap and suspicious recharge alerts. Confirmed fraud triggers automatic account protection.
**FRs covered:** FR-53, FR-54, FR-55, FR-56, FR-60, FR-61, FR-62, FR-66, FR-72 (fraud traces)

### Epic 7: Ops & Marketing Dashboard (TDD-first)
The operations team can monitor plan stock and order fulfilment. The marketing team can forecast subscriber growth, build targeted upsell segments using LLM-powered labelling, and receive textual strategy recommendations. Engineering can diagnose billing issues via the Root Cause Analysis Agent.
**FRs covered:** FR-42, FR-43, FR-44, FR-45, FR-46, FR-47, FR-48, FR-49, FR-50, FR-51, FR-52, FR-72 (ops traces), FR-73 (upsell rubric), FR-75

<!-- Stories begin below — one section per epic -->

---

## Epic 1: Core Infrastructure, Tooling & Subscriber Identity

Subscribers can register, verify their identity, log in, manage their profile, and access the system securely. The full development infrastructure (Podman Compose, Postgres, Flyway, CI/CD, observability stack) is set up and operational. This epic is the hard prerequisite for all other epics.

---

### Story 1.1: UX Brief — Subscriber Registration & Identity Flows

As a **product team**,
I want a lightweight UX brief defining screen layouts, component names, and key interactions for subscriber registration, login, and profile flows,
So that frontend stories in this epic have a clear, agreed-upon design target and the developer agent can implement consistent, named components.

**Acceptance Criteria:**

**Given** no UX design document exists and PRD user journey UJ-1 defines the subscriber identity flow
**When** the UX brief is produced
**Then** it documents screen names and routes for: /register (multi-step form), /activate (order tracker), /login, /profile, /profile/kyc, /profile/payment-methods
**And** it specifies the four role-gated route prefixes: /subscriber/*, /ops/*, /fraud/*, /simulator/* (UX-DR7)
**And** it lists shared UI component names to be created in components/ui/: Button, Card, Badge, Table, Modal (UX-DR8)
**And** it describes the registration multi-step form: Step 1 (personal details), Step 2 (TRAI CAF fields), Step 3 (Registration ID display + OTP entry)
**And** it specifies the SIM activation order tracker: step indicator showing Created → KYC Pending → KYC Verified → Activated states
**And** it defines PascalCase.tsx naming convention for all components and usePascalCase.ts for hooks (UX-DR8)

---

### Story 1.2: Podman Compose Stack, Postgres Init & Flyway Baseline

As a **developer**,
I want a fully reproducible local development environment that starts all infrastructure services with a single command and initialises Postgres with the required extensions, roles, and schema baseline,
So that any team member can onboard in under 15 minutes and all services share a consistent data layer.

**Acceptance Criteria:**

**Given** Podman and Podman Compose are installed
**When** `just up` is run
**Then** the dependency stack starts: Redpanda, Valkey (noeviction policy), Postgres 16, LangFuse (self-hosted), MiniStack (Cognito + S3), OTEL-TUI, Fluentd
**And** the Postgres init scripts execute in order at container creation: 01_extensions.sql (pg_uuidv7, pgcrypto, pg_trgm, btree_gin), 02_roles.sql (app_rw, app_ro, migration_user), 03_databases.sql (sboai_db)
**And** Flyway runs V1__baseline_schema.sql creating the initial schema (subscribers, subscriber_orders, audit_log tables) with UUIDv7 primary keys on transactional tables and UUIDv4 on reference tables (ARCH-9)
**And** the two-file Podman Compose split is in place: docker-compose-dependencies.yaml (infra only) and docker-compose.yaml (full stack via include:) (ARCH-28)
**And** named volumes persist across restarts: postgres_data, ministack_cognito, ministack_s3, milvus_lite_data (ARCH-29)
**And** `just deps` starts only infra (no app containers) for local backend development

---

### Story 1.3: Project Tooling — justfile, GitHub Actions CI, Linters & README

As a **developer**,
I want a cross-platform task runner, automated CI pipeline, and configured linters so that all contributors run identical commands regardless of OS and every PR is validated before merge,
So that code quality is enforced automatically and onboarding requires no tribal knowledge.

**Acceptance Criteria:**

**Given** the project root exists with both cdr-pipeline/ and service_backend/ codebases
**When** the tooling is configured
**Then** justfile defines these commands: `just deps`, `just up`, `just migrate`, `just seed`, `just seed-milvus`, `just test`, `just lint` (ARCH-18)
**And** ruff is configured in pyproject.toml with lint + format rules for both Python codebases; pyrefly configured for static type checking (ARCH-20)
**And** ESLint + TypeScript strict mode configured in frontend/; Vitest configured for unit tests (ARCH-20)
**And** GitHub Actions workflow runs `uv tox` on every PR executing: lint, typecheck, test — all three must pass before merge (ARCH-19)
**And** README.md at project root contains: Prerequisites section, MVP Setup (6 steps: clone → deps → up → migrate → seed → open), Target State Setup section stub, architecture diagram reference (ARCH-30)
**And** .env.example is committed with all required environment variable keys; .env is gitignored (ARCH-17)

---

### Story 1.4: pydantic-settings Singleton, Health Endpoints & OTEL Trace Middleware

As a **platform engineer**,
I want each service to load its configuration exactly once at startup, expose /health and /ready endpoints, and propagate OTEL trace IDs through every request,
So that misconfigured deployments fail fast at boot and every request is traceable end-to-end.

**Acceptance Criteria:**

**Given** both cdr-pipeline and service_backend services exist
**When** either service starts
**Then** a pydantic-settings singleton loads all required env vars at module import time and raises a descriptive error immediately if any required value is missing (ARCH-17)
**And** service_backend exposes GET /health and GET /ready; both respond within 200ms under normal operating conditions (FR-77, NFR-19)
**And** GET /health returns 200 with `{"status": "ok"}` when the service is running
**And** GET /ready returns 200 only when Postgres connection pool and Valkey connection are healthy; returns 503 otherwise
**And** OTEL trace middleware in FastAPI extracts traceparent from incoming request headers; generates a new root span if absent (ARCH-27)
**And** trace_id is stored in request.state.trace_id and returned in the X-Trace-Id response header on every response
**And** PII never appears in OTEL span attributes; only subscriber UUID or MSISDN[-4:] suffix is used (NFR-16, ARCH-32)

---

### Story 1.5: LangFuse Self-Hosted Setup & Client Instrumentation Scaffold

As a **platform engineer**,
I want LangFuse running locally and a reusable instrumentation client wired into service_backend so that all future agentic workflows can emit traces with a single decorator,
So that agent observability is available from the first agent story without per-agent setup overhead.

**Acceptance Criteria:**

**Given** LangFuse is included in docker-compose-dependencies.yaml
**When** `just up` is run
**Then** LangFuse UI is accessible at http://localhost:3000 and accepts traces
**And** a `get_langfuse_client()` singleton factory is implemented in service_backend/core/observability/langfuse.py
**And** a `@trace_agent` decorator is implemented that wraps any async function, creates a LangFuse trace with: trace name, input, output, model, token usage (FR-72)
**And** the decorator is a no-op (pass-through) when LANGFUSE_ENABLED=false in env, allowing tests to run without a live LangFuse instance
**And** `just up` logs the LangFuse dashboard URL after startup

---

### Story 1.6: Subscriber Registration, TRAI CAF & PII Encryption

As a **new subscriber**,
I want to submit an online sign-up form with my personal details and TRAI Customer Acquisition Form fields and receive a unique Registration ID,
So that I can begin the SIM activation process and my identity is on record before my SIM is active.

**Acceptance Criteria:**

**Given** a visitor navigates to /register
**When** they complete the multi-step registration form (personal details → TRAI CAF fields → submission)
**Then** a subscriber record is created in Postgres with a UUIDv7 primary key and status = 'REGISTRATION_COMPLETE'
**And** a unique Subscriber Registration ID (human-readable: REG-{YYYYMMDD}-{8 hex chars}) is generated and displayed to the subscriber
**And** PII fields (name, address, MSISDN if provided) are encrypted at rest using pgcrypto AES-256 (FR-63, NFR-6)
**And** the TRAI CAF submission is recorded in the audit_log table as an immutable row with event_type = 'TRAI_CAF_SUBMITTED', timestamp, and a hash of the submitted data (FR-3, FR-65)
**And** all data is stored within the India-region Postgres instance (NFR-3)
**And** the registration API response uses the standard FastAPI envelope: `{data: {registration_id, status}, meta: {trace_id, timestamp}}` (ARCH-12)
**And** registration writes to the existing **V1-baseline** tables — `identity_subscribers`, `identity_registrations`, `identity_caf_submissions`, `billing_audit_log` (append-only) — and creates an initial `ops_order_fulfilment` order; **NO new migration is created** (V1 is the full all-domain baseline — see Story 1.2). [`V2__subscriber_schema.sql` and the `subscribers`/`subscriber_orders`/`audit_log` shorthand are superseded.]

**Given** a registration form is submitted with a duplicate MSISDN
**When** the API receives the request
**Then** it returns HTTP 409 with error code DUPLICATE_MSISDN

---

### Story 1.7: SIM Activation Order Tracker UI

As a **new subscriber**,
I want to see a step-by-step visual tracker showing my SIM order's current fulfilment state,
So that I know exactly where I am in the activation process and what to expect next.

**Acceptance Criteria:**

**Given** a subscriber is logged in with a Registration ID and has an `ops_order_fulfilment` order record (the canonical SIM-order table; "subscriber_order" is shorthand)
**When** they navigate to /activate
**Then** the UI displays an order tracker with four steps: Created → KYC Pending → KYC Verified → Activated
**And** the current step is visually highlighted; completed steps show a checkmark
**And** the tracker polls GET /api/v1/subscriber/orders/{order_id}/status every 10 seconds and updates without a full page reload
**And** when status = 'ACTIVATED', a success banner displays with the subscriber's MSISDN
**And** the API endpoint GET /api/v1/subscriber/orders/{order_id}/status returns `{status, updated_at, msisdn}` (only when ACTIVATED)
**And** there are **two distinct activation flows**: (1) the subscriber-facing read-only tracker at `frontend/src/portals/subscriber/SimActivation.tsx` (route `/activate`), and (2) a separate developer tool at `frontend/src/portals/simulator/SimActivation.tsx` (under `/simulator/*`) that simulates/advances an order's fulfilment state for testing. [Corrects the earlier `frontend/src/pages/subscriber/` path.]

---

### Story 1.8: Login, OTP Step-Up & JWT Role-Based Auth

As a **subscriber or operator**,
I want to log in with my credentials and complete OTP step-up verification so I receive a JWT with my role claim,
So that I can access my role-specific dashboard and all API calls are authenticated.

**Acceptance Criteria:**

**Given** a pre-activation subscriber navigates to /login
**When** they enter their Registration ID + password
**Then** MiniStack Cognito Custom Auth Flow initiates and sends an OTP to their registered email/phone
**And** on correct OTP entry, a JWT is issued with role claim = 'subscriber' and the subscriber's UUID in the sub claim

**Given** a post-activation subscriber enters MSISDN + password
**When** authentication succeeds
**Then** the JWT role claim = 'subscriber' and MSISDN is in the token payload

**Given** any authenticated user holds a valid JWT
**When** they navigate to a role-gated route (/subscriber/*, /ops/*, /fraud/*, /simulator/*)
**Then** the React SPA reads the JWT role claim and renders only the matching route prefix; mismatched role → redirect to /login (UX-DR7, FR-67)

**Given** a JWT is present in localStorage
**When** any API request is made
**Then** the JWT is sent as Authorization: Bearer {token} and the FastAPI JWT middleware validates the signature, expiry, and role claim before routing the request (NFR-7)

**And** **NO sessions table is created** — JWTs are **stateless** (issued by Cognito). Token revocation is performed via the Cognito admin API (account disable + token revocation), and the 30-minute access-token TTL bounds the revocation gap (architecture §1.8.1/§1.8.2). [The earlier `V3__auth_schema.sql`/`auth_sessions` design is superseded — there is no sessions table in the canonical §1.7.1 inventory.]

---

### Story 1.9: Profile Management & KYC Status View

As an **authenticated subscriber**,
I want to view and edit my personal details and see my current KYC verification status,
So that my account information stays accurate and I understand what actions are available to me.

**Acceptance Criteria:**

**Given** a subscriber is logged in and navigates to /subscriber/profile
**When** the page loads
**Then** their decrypted name, email, saved address, and KYC status are displayed
**And** KYC status is shown as one of: Verified (green badge), Pending (amber badge), Rejected (red badge with reason) (FR-7)

**Given** a subscriber edits their address or email and submits
**When** the PATCH /api/v1/subscriber/profile request is processed
**Then** the updated PII fields are re-encrypted at rest and the audit_log records an UPDATE_PROFILE event (FR-5)
**And** the API returns 200 with the updated (decrypted) profile in the standard envelope

**Given** a subscriber's KYC status is 'REJECTED'
**When** they view their profile
**Then** a rejection reason is displayed and a link to re-submit KYC documents is shown

---

### Story 1.10: Saved Payment Methods & PCI-DSS Tokenisation

As an **authenticated subscriber**,
I want to add and manage saved payment methods (credit card, UPI, net banking, mobile wallet) with card numbers tokenised at the point of entry,
So that I can recharge quickly without re-entering payment details and my card data is never stored in plain text.

**Acceptance Criteria:**

**Given** a subscriber navigates to /subscriber/profile/payment-methods
**When** they add a credit card
**Then** the card number is tokenised client-side before leaving the browser; only the token and last-4 digits are stored in Postgres (FR-6, FR-64, NFR-5)
**And** raw PAN is never present in any API payload, log, database column, or OTEL span (NFR-5, NFR-16)
**And** the payment_methods table stores: payment_method_id (UUIDv4), subscriber_id, type (CREDIT_CARD | UPI | NET_BANKING | MOBILE_WALLET), token, display_label, is_default

**Given** a subscriber adds a UPI ID or net banking account
**When** the record is saved
**Then** no tokenisation is applied (these are not card numbers); the identifier is stored as-is

**Given** a subscriber has multiple saved payment methods
**When** they view /subscriber/profile/payment-methods
**Then** all saved methods are listed with type icon, display label (e.g., "•••• 4242"), and a "Set Default" action
**And** a Flyway migration (V4__payment_schema.sql) creates: payment_methods table

---

## Epic 2: CDR Pipeline, Balance Engine, Synthetic Data & Simulator Tools

The real-time CDR ingestion pipeline is operational: events ingested from Redpanda, balances deducted deterministically in Valkey and flushed to Postgres, audit log written, and trace IDs propagated end-to-end. A synthetic dataset (1K plans, 300K subscribers, 5M CDRs) is generated for all downstream testing. The simulator dashboard gives developers full end-to-end visibility.

---

### Story 2.1: Redpanda Topic Provisioning & Kafka Envelope Contract

As a **platform engineer**,
I want all Redpanda topics created with correct partition counts and a standard event envelope enforced across producers,
So that all pipeline components can communicate reliably and every event is traceable.

**Acceptance Criteria:**

**Given** Redpanda is running via Podman Compose
**When** `just up` completes
**Then** the following topics exist with the specified partition counts: cdr.raw (24p), cdr.enriched.filtered (24p), cdr.fraud.flagged (6p), fraud.alerts (6p), notification.events (12p), cdr.dlq (6p) (ARCH-10)
**And** a topic provisioning script (scripts/provision_topics.py) creates topics idempotently (safe to re-run)
**And** the Kafka event envelope schema is defined in a shared Pydantic model: `{event_type, event_id (UUIDv7), trace_id, timestamp, payload}` (ARCH-11)
**And** traceparent is set in the Kafka message header AND trace_id is in the JSON body on every message (ARCH-11, NFR-17)
**And** cdr.raw topic key = subscriber_id to ensure per-subscriber ordering

---

### Story 2.2: CDR Ingestion Consumer — Dedup & DLQ

As a **platform engineer**,
I want the CDR pipeline to consume events from cdr.raw, deduplicate them idempotently using Valkey, and route failed events to the dead-letter queue,
So that each CDR is processed exactly once and no event is silently lost.

**Acceptance Criteria:**

**Given** a CDR event is published to cdr.raw
**When** the aiokafka consumer pool processes it
**Then** the consumer checks `dedup:{cdr_id}` in Valkey (24h TTL SET NX); if the key already exists, the event is discarded with a deduplicated counter increment (FR-57, NFR-9, ARCH-5)
**And** if the key does not exist, the event is validated against the CDR schema and forwarded to cdr.enriched.filtered
**And** if schema validation fails, the raw event is published to cdr.dlq with error metadata (ARCH-10, FR-57)
**And** the consumer pool uses aiokafka with async processing; consumer count matches partition count (24) (ARCH-15)
**And** `cdr-pipeline/src/pipeline/consumer.py` implements the consumer loop; dedup logic is in `pipeline/dedup.py`

**Given** the cdr-pipeline service restarts
**When** it starts up
**Then** it resumes from the last committed Kafka offset — no events are re-processed from scratch

---

### Story 2.3: Balance Deduction Engine — Valkey Write Buffer & Postgres Flush

As a **platform engineer**,
I want the balance deduction engine to atomically deduct charges from a Valkey write buffer and periodically flush to Postgres, with the P95 latency target of 200ms met,
So that balance deductions are fast, idempotent, and durable.

**Acceptance Criteria:**

**Given** a validated CDR event arrives from cdr.enriched.filtered
**When** the balance engine processes it
**Then** the charge amount is deducted from `balance:{msisdn}` in Valkey using INCRBY (negative value) within P95 ≤ 200ms from CDR receipt (FR-58, NFR-1)
**And** the deduction is idempotent: a second CDR with the same cdr_id returns without modifying the balance (NFR-9)
**And** the updated balance is flushed to the wallet_balance table in Postgres via async bulk upsert on a configurable interval (default: 500ms or 100 events, whichever comes first)
**And** `balance:{msisdn}` keys are never evicted (Valkey maxmemory-policy = noeviction) (ARCH-6)
**And** on cdr-pipeline restart, `load_balances_from_postgres()` re-seeds all balance keys before the consumer loop starts (ARCH-6)
**And** a Flyway migration (V5__billing_schema.sql) creates: wallet_balance (msisdn, balance_paise, updated_at), billing_audit_log (cdr_id, msisdn, charge_paise, balance_after_paise, processed_at), cdr_dedup (cdr_id, processed_at, TTL-managed by Valkey)
**And** talktime deduction uses per-second voice rate from the subscriber's active plan; unlimited-bundle deduction logs the event with zero charge

---

### Story 2.4: Audit Log & Distributed Trace Propagation

As a **platform engineer**,
I want every billing event written to an immutable audit log and the trace ID propagated across the full CDR → balance → fraud → notification pipeline,
So that every charge is forensically traceable and TRAI 6-year retention is met.

**Acceptance Criteria:**

**Given** a CDR event is processed by the balance engine
**When** the deduction completes
**Then** a row is appended to billing_audit_log with: cdr_id, subscriber_id, event_type, charge_paise, balance_after_paise, trace_id, processed_at (FR-59, NFR-4)
**And** the billing_audit_log table has no UPDATE or DELETE grants for the app_rw role — append-only enforced at the DB layer (FR-59)
**And** trace_id from the CDR event envelope is included in: the billing_audit_log row, the cdr.enriched.filtered message header, the fraud.flagged message header, and the notification.events message (FR-76, ARCH-11)
**And** the OTEL span for balance deduction references the same trace_id as the upstream CDR producer span

---

### Story 2.5: CDR Management API — DLQ Inspect & Worker Control

As a **developer or operator**,
I want API endpoints to inspect the dead-letter queue and pause/resume CDR workers,
So that I can diagnose pipeline failures and safely halt processing without restarting containers.

**Acceptance Criteria:**

**Given** events exist in cdr.dlq
**When** GET /api/v1/admin/dlq is called with a valid admin JWT
**Then** it returns a paginated list of DLQ events with: cdr_id, error_reason, original_topic, failed_at, raw_payload preview
**And** GET /api/v1/admin/dlq/{cdr_id} returns the full raw payload for a single event

**Given** an operator calls POST /api/v1/admin/workers/pause
**When** the request is processed
**Then** all CDR consumer coroutines stop polling new messages within 2 seconds; the endpoint returns `{status: "paused"}`
**And** POST /api/v1/admin/workers/resume resumes polling and returns `{status: "running"}`
**And** both endpoints require role claim = 'admin' in the JWT

---

### Story 2.6: Synthetic Dataset Generation — Plans, Subscribers & CDRs

As a **developer**,
I want a script that generates a realistic synthetic dataset (1K plans, 300K subscribers, 5M CDRs) following the correct creation order,
So that all downstream epics have representative data for testing agents, forecasts, and billing flows.

**Acceptance Criteria:**

**Given** Flyway migrations V1–V5 have run
**When** `just seed` is executed
**Then** Step 1: V5 migration (already run by Flyway) has seeded 1,000 plans with UUIDv4 primary keys, realistic Indian telecom plan names, validity (28/56/84 days), data allowance, voice, SMS quotas, and price in paise (ARCH-24)
**And** Step 2: `scripts/generate_synthetic_data.py` inserts 300,000 subscribers via psycopg3 COPY protocol in batches of 50,000; each subscriber references a valid plan_id (ARCH-24)
**And** Step 3: the same script generates 5,000,000 CDR records (UUIDv7) referencing valid subscriber MSISDNs; events span 90 days; CDR types distributed: voice 60%, data 30%, SMS 10%
**And** approximately 0.5% of subscribers have embedded fraud signals: unusual CDR velocity (>200 events/day) and/or SIM swap flag = true (ARCH-25)
**And** SOP knowledge base is seeded via `scripts/sop_generator.py` writing to sop_rules and sop_knowledge_chunks tables (ARCH-26)
**And** `just seed` is idempotent — re-running truncates and re-seeds without error
**And** seed completion logs: plans count, subscribers count, CDR count, fraud-flagged subscribers count

---

### Story 2.7: Milvus Lite Initialisation & Vector Seeding

As a **developer**,
I want Milvus Lite running embedded in service_backend and all three vector collections seeded from the synthetic knowledge base,
So that RAG-dependent stories in Epic 5 (chatbot) and Epic 7 (RCA agent) have a populated vector store from day one.

**Acceptance Criteria:**

**Given** service_backend starts
**When** the Milvus Lite client initialises
**Then** it connects to the embedded Milvus Lite DB at /app/data/milvus/sboai.db (Podman volume: milvus_lite_data) (ARCH-7)
**And** three collections are created if not present: faq_chunks (fields: chunk_id, text, embedding[1536], category, source_doc, plan_type), plan_vectors (fields: plan_id, text, embedding[1536], plan_type, price, validity), sop_chunks (fields: chunk_id, text, embedding[1536], rule_id, severity, domain) (ARCH-8)
**And** each collection uses HNSW index and supports BM25 + RRF hybrid search (ARCH-8)

**Given** `just seed-milvus` is run after `just seed`
**When** the seeding script executes
**Then** plan_vectors collection is populated from the plans table (1K vectors via text-embedding-3-small, 1536 dims)
**And** faq_chunks is populated from a static FAQ YAML file (minimum 50 FAQ entries)
**And** sop_chunks is populated from sop_knowledge_chunks table
**And** `just seed-milvus` is idempotent — drops and re-creates collections on re-run

---

### Story 2.8: CDR Simulator UI — Form, Dispatch & WebSocket Trace Display

As a **developer or admin**,
I want a UI to generate synthetic CDR events and watch the end-to-end trace logs update in real time,
So that I can verify pipeline behaviour without needing external tooling.

**Acceptance Criteria:**

**Given** a user with role = 'admin' is on /simulator/cdr
**When** they fill in the CDR parameter form (subscriber MSISDN, event type, duration/data MB, timestamp) and click Dispatch
**Then** POST /api/v1/simulator/cdr publishes one CDR event to cdr.raw with a fresh trace_id (FR-68)
**And** the WebSocket at ws://localhost:8000/ws/simulator/trace streams pipeline stage updates: Received → Deduped → Balance Deducted → Notification Queued
**And** each pipeline stage update includes: stage name, timestamp, trace_id, and any error if applicable (NFR-15)
**And** 100% of dispatched events must appear in the trace stream (NFR-15)
**And** the CdrSimulator.tsx component lives in frontend/src/pages/simulator/

---

### Story 2.9: SIM Activation Simulator & Notification Portal

As a **developer or admin**,
I want an admin action to advance a subscriber's order to Activated status and a live Notification Portal to observe all simulated messages,
So that the full subscriber lifecycle can be exercised end-to-end during development.

**Acceptance Criteria:**

**Given** a user with role = 'admin' is on /simulator/sim-activation
**When** they select a subscriber (by MSISDN or Registration ID) and click Activate
**Then** POST /api/v1/simulator/activate updates the subscriber_order status to 'ACTIVATED' and generates the subscriber's MSISDN (FR-70)
**And** the subscriber's balance key is seeded in Valkey: `balance:{msisdn}` = plan's initial wallet credit in paise

**Given** any simulated SMS, push notification, or OTP is triggered by the system
**When** the notification.events Kafka topic receives the event
**Then** a WebSocket consumer at ws://localhost:8000/ws/notifications broadcasts the event to the Notification Portal UI (FR-69)
**And** the NotificationPortal.tsx displays a live-updating list with: subscriber MSISDN[-4:], notification type, message content preview, timestamp
**And** the portal is accessible at /simulator/notifications

---

## Epic 3: Subscriber Self-Care Portal

Subscribers can view their real-time balance and usage, browse plans, make recharges, download PDF receipts, and view transaction history through the web portal.

---

### Story 3.1: UX Brief — Balance, Usage & Recharge Portal Flows

As a **product team**,
I want a lightweight UX brief defining screen layouts, component names, and key interactions for the subscriber self-care portal,
So that frontend stories have a clear, agreed-upon design target.

**Acceptance Criteria:**

**Given** PRD user journey UJ-2 defines the self-care portal flows
**When** the UX brief is produced
**Then** it documents routes and screen names: /subscriber/dashboard (balance card + usage rings), /subscriber/plans (catalogue with filter/sort), /subscriber/recharge (plan select → payment → confirmation), /subscriber/history (transaction ledger), /subscriber/receipts/{id} (PDF download)
**And** it specifies the balance card component: large INR balance figure, zero-balance warning state, last-updated timestamp
**And** it defines usage breakdown display: circular progress rings per type (voice minutes, data MB/GB, SMS count, roaming)
**And** it specifies plan catalogue card: plan name, validity badge, data/voice/SMS quota chips, price, "Recharge" CTA
**And** it defines the recharge flow: Step 1 (plan select), Step 2 (payment method select or add new), Step 3 (confirmation + PDF download link)
**And** shared chart components to be created in components/charts/: UsageRing (Recharts wrapper) (UX-DR2, UX-DR8)

---

### Story 3.2: Real-Time Balance Display & Usage Breakdown

As an **authenticated subscriber**,
I want to see my current prepaid wallet balance and per-type usage breakdown on my dashboard,
So that I always know how much credit I have and how I've used my plan allowances.

**Acceptance Criteria:**

**Given** a subscriber is logged in and navigates to /subscriber/dashboard
**When** the page loads
**Then** GET /api/v1/subscriber/balance returns the current balance in paise, rendered as INR with 2 decimal places (FR-8)
**And** the balance reflects the latest Valkey value (read from `balance:{msisdn}`) — not a stale DB read
**And** if balance = 0, the UI shows a "Balance depleted" warning banner with a "Recharge Now" CTA (FR-8)
**And** GET /api/v1/subscriber/usage returns per-type consumption for the current plan period: voice_minutes_used, data_mb_used, sms_count_used, roaming_mb_used (FR-10)
**And** usage rings display used vs. total allowance for each type; "Unlimited" label shown when plan has no cap

**Given** a CDR deduction occurs
**When** the subscriber views the dashboard within 5 seconds
**Then** a manual refresh of the balance API reflects the updated balance

---

### Story 3.3: Transaction History Ledger

As an **authenticated subscriber**,
I want to view a paginated list of all my charges, recharges, and refunds with timestamps and CDR references,
So that I can audit my account activity and understand every deduction.

**Acceptance Criteria:**

**Given** a subscriber navigates to /subscriber/history
**When** the page loads
**Then** GET /api/v1/subscriber/transactions returns a paginated ledger (default 20 rows/page) of: transaction_type (CHARGE | RECHARGE | REFUND), amount_paise, balance_after_paise, cdr_reference (nullable), description, created_at (FR-9)
**And** entries are sorted by created_at descending (newest first)
**And** the UI supports page navigation (prev/next) via React Query with cursor-based pagination
**And** each CHARGE row displays the CDR reference as a copyable code
**And** the ledger is immutable — no edit or delete UI exists (FR-9)

---

### Story 3.4: Plan Details View & Plan Catalogue

As an **authenticated subscriber**,
I want to view my active plan details and browse all available plans with filter and sort options,
So that I can understand my current entitlements and make informed recharge decisions.

**Acceptance Criteria:**

**Given** a subscriber has an active plan
**When** they view /subscriber/dashboard
**Then** a plan details card displays: plan name, validity expiry date in IST format (DD MMM YYYY), bundled quotas (data GB, voice minutes, SMS count), remaining allowances (FR-11)
**And** days remaining until expiry is shown as a countdown; plans expiring within 3 days show an amber warning badge

**Given** a subscriber navigates to /subscriber/plans
**When** the plan catalogue loads
**Then** GET /api/v1/plans returns all active plans with: name, data_gb, voice_minutes, sms_count, validity_days, price_paise, plan_type (FR-12)
**And** the catalogue supports client-side filter by validity (28d / 56d / 84d / all) and sort by price (asc/desc) and data (desc)
**And** the subscriber's current active plan is highlighted with a "Current Plan" badge

---

### Story 3.5: Recharge Purchase — Plan Selection & Simulated Payment

As an **authenticated subscriber**,
I want to select a plan, choose a payment method, and complete a simulated recharge,
So that my wallet is topped up and my plan is activated immediately.

**Acceptance Criteria:**

**Given** a subscriber selects a plan and clicks "Recharge"
**When** they proceed through the recharge flow
**Then** they can select a saved payment method or add a new one; all payments are simulated (no real gateway) (FR-13, FR-14)
**And** POST /api/v1/subscriber/recharge accepts: plan_id, payment_method_id, idempotency_key (client-generated UUIDv7) (FR-16)
**And** the API responds within 3 seconds with: transaction_id, new_balance_paise, plan_activation_timestamp, receipt_url
**And** the subscriber's wallet balance is credited in Valkey (`balance:{msisdn}` INCRBY) and flushed to Postgres
**And** the subscriber's active_plan record is updated with the new plan and expiry date

**Given** the same recharge request is retried with the same idempotency_key
**When** the API receives the duplicate
**Then** it returns HTTP 200 with the original transaction result — no double-charge occurs (FR-16)

**Given** a payment method of type CREDIT_CARD is selected
**When** the recharge is submitted
**Then** only the payment token is used — raw PAN is never sent to the server (FR-64)

---

### Story 3.6: PDF Receipt Generation

As an **authenticated subscriber**,
I want to download a PDF receipt for each completed recharge transaction,
So that I have a permanent record for my financial records.

**Acceptance Criteria:**

**Given** a recharge transaction is completed
**When** the subscriber clicks the receipt download link (receipt_url)
**Then** GET /api/v1/subscriber/receipts/{transaction_id} generates and streams a PDF receipt (FR-15)
**And** the PDF contains: subscriber name (decrypted), MSISDN[-4:], transaction date (IST), plan name, amount paid (INR), payment method type, transaction ID, operator logo placeholder
**And** the PDF is generated by WeasyPrint from an HTML template
**And** the response Content-Type is application/pdf with Content-Disposition: attachment; filename="receipt_{transaction_id}.pdf"
**And** PII (full MSISDN, full name) in the PDF is limited to what is legally required; no card numbers appear

---

### Story 3.7: Refund View

As an **authenticated subscriber**,
I want to view a list of my failed recharge transactions that would be eligible for refund,
So that I know which transactions did not complete and can follow up if needed.

**Acceptance Criteria:**

**Given** a subscriber navigates to /subscriber/history and filters by type = REFUND_ELIGIBLE
**When** the page renders
**Then** GET /api/v1/subscriber/transactions?type=FAILED returns all failed recharge transactions for the subscriber (FR-17)
**And** each row shows: transaction_id, plan_attempted, amount_paise, failure_reason, created_at
**And** a banner states: "Actual refund processing is handled by the operator's billing team. Contact support for assistance."
**And** no "Request Refund" button exists — actual refund processing is out of MVP scope (FR-17)

---

## Epic 4: Notifications & USSD Interface

Subscribers receive proactive balance and plan alerts via simulated SMS/push. They can also self-serve via USSD: balance check, plan info, recharge initiation, and notification preference management. Rate limiting is enforced on USSD and API channels.

---

### Story 4.1: Notification Service — Low Balance, Depletion & Plan Expiry Alerts

As a **subscriber**,
I want to receive simulated SMS and push notifications when my balance drops low, depletes, or my plan is about to expire,
So that I can recharge proactively before service is interrupted.

**Acceptance Criteria:**

**Given** a CDR deduction reduces a subscriber's balance below ₹10 (1000 paise)
**When** the balance engine flushes to Postgres
**Then** a notification event is published to notification.events with type = LOW_BALANCE, subscriber_id, balance_paise, trace_id (FR-18)
**And** the threshold value (1000 paise default) is read from a DB config record (key = 'low_balance_threshold_paise') — not hardcoded (NFR-20)

**Given** a subscriber's balance reaches 0
**When** the balance engine processes the deduction
**Then** a BALANCE_DEPLETED notification event is published to notification.events (FR-19)

**Given** a scheduled job runs once daily at 08:00 IST
**When** it finds subscribers whose plan expires within 3 days
**Then** a PLAN_EXPIRY_REMINDER notification event is published for each affected subscriber (FR-20)
**And** the lead-time (3 days default) is read from a DB config record (key = 'plan_expiry_reminder_days') (NFR-20)

**Given** a CDR deduction reduces a subscriber's data allowance below 10%
**When** the balance engine calculates remaining data
**Then** a DATA_NUDGE notification event is published to notification.events (FR-21)
**And** all notification events follow the Kafka event envelope schema (ARCH-11)

---

### Story 4.2: Notification Preferences & Delivery Simulation

As a **subscriber**,
I want to manage which notification types I receive and have the system respect my preferences,
So that I only receive alerts I've opted into.

**Acceptance Criteria:**

**Given** a subscriber is logged in and navigates to /subscriber/profile/notifications
**When** the page loads
**Then** GET /api/v1/subscriber/notification-preferences returns their current opt-in status for each type: LOW_BALANCE, BALANCE_DEPLETED, PLAN_EXPIRY_REMINDER, DATA_NUDGE
**And** the subscriber can toggle each preference on/off; PATCH /api/v1/subscriber/notification-preferences persists the change

**Given** a notification event is consumed from notification.events
**When** the notification dispatcher processes it
**Then** it checks the subscriber's preferences; if opted out, the event is acknowledged and discarded without sending
**And** if opted in, the notification is logged to the notifications table as simulated delivery (no real SMS/push gateway in MVP)
**And** the notification is also published to the Notification Portal WebSocket (from Story 2.9)
**And** a Flyway migration creates: notification_preferences table (subscriber_id, type, opted_in, updated_at), notifications table (notification_id UUIDv7, subscriber_id, type, content, delivered_at, simulated=true)

---

### Story 4.3: Rate Limiting — Per-Subscriber 100 RPM

As a **platform engineer**,
I want a rate limiter that enforces 100 requests per minute per subscriber across API and USSD channels,
So that no single subscriber can overload the system and the limit is adjustable without a code deploy.

**Acceptance Criteria:**

**Given** a subscriber makes requests to any API endpoint
**When** they exceed 100 requests within a 60-second sliding window
**Then** subsequent requests return HTTP 429 with body `{error: {code: "RATE_LIMIT_EXCEEDED", message: "100 RPM limit reached. Try again in {retry_after}s"}}` (FR-36)
**And** the rate limit is enforced using Valkey with key pattern `ratelimit:{msisdn}:{minute_bucket}` with 60s TTL
**And** the limit value (100 RPM default) is read from DB config record (key = 'rate_limit_rpm') — not hardcoded (NFR-20)
**And** the rate limit applies separately per channel: api, ussd, chatbot — a subscriber at API limit is not blocked on USSD

---

### Story 4.4: USSD Session Handler & Menu Router

As a **subscriber**,
I want to use USSD to access a text menu for balance, plan info, recharge, and notification preferences,
So that I can self-serve from any basic phone without internet access.

**Acceptance Criteria:**

**Given** the telecom operator sends a USSD callback to POST /api/v1/ussd/callback
**When** the request body contains: msisdn, session_id, button_pressed, ussd_string
**Then** the handler retrieves or initialises session state from Valkey HASH `session:{session_id}` with 30-minute TTL (FR-37, ARCH-5)
**And** the response body is a structured text menu string per USSD protocol format

**Given** a subscriber dials the USSD code (session start, button_pressed = empty)
**When** the root menu is displayed
**Then** the response is: "Welcome\n1. Balance\n2. My Plan\n3. Recharge\n4. Notifications\n0. Exit"

**Given** a subscriber selects option 1 (Balance)
**When** the handler processes button_pressed = "1"
**Then** it reads `balance:{msisdn}` from Valkey and responds: "Your balance is ₹{X.XX}\n0. Back" (FR-38)

**Given** a subscriber selects option 2 (My Plan)
**When** the handler processes button_pressed = "2"
**Then** it responds with active plan name, validity expiry, and remaining data/voice/SMS (FR-39)

**Given** a subscriber selects option 3 (Recharge) and then a plan
**When** the handler processes the selection
**Then** it displays a confirmation screen with the plan price and "Press 1 to confirm" (FR-40)
**And** on confirmation, POST /api/v1/subscriber/recharge is called internally with a default saved payment method; result is shown as USSD text

**Given** a subscriber selects option 4 (Notifications)
**When** the handler processes the selection
**Then** it shows current opt-in status per type and allows toggling via button press (FR-41)

---

## Epic 5: Self-Care Chatbot — Multi-Agent (TDD-first)

Subscribers can resolve billing queries, understand charges, raise disputes, get plan recommendations, and initiate recharges through an intelligent multi-agent chatbot with RAG, A2A communication, and full LangFuse observability. Eval harness is written first.

---

### Story 5.1: UX Brief — Chatbot Interface & AG-UI Stream Flows

As a **product team**,
I want a lightweight UX brief defining the chatbot UI layout, AG-UI event handling, and tool-call visualisation patterns,
So that chatbot frontend stories have a clear design target.

**Acceptance Criteria:**

**Given** PRD user journey UJ-3 defines the chatbot self-service flow
**When** the UX brief is produced
**Then** it documents the CopilotChat component placement: embedded bottom-right panel in the /subscriber/* layout, collapsible
**And** it defines how tool-call results are visualised: charge breakdown → collapsible table, plan recommendation → plan card with Accept/Dismiss buttons, ticket creation → confirmation banner with ticket ID
**And** it specifies the session-end summary notification toast behaviour
**And** it defines useCopilotReadable hook names: useSubscriberBalance, useActivePlan, useChatSession (UX-DR3, ARCH-23)
**And** it confirms the CopilotKit runtime URL: POST /api/chat/stream (ARCH-13)

---

### Story 5.2: Eval Harness — LLM-as-Judge & DeepEval Scaffolding

As a **QA engineer**,
I want an evaluation harness with LLM-as-Judge rubrics and DeepEval metrics wired up before any agent code is written,
So that every agent story can be validated against quality targets from the first implementation.

**Acceptance Criteria:**

**Given** the eval harness is set up
**When** `just test` runs the eval suite
**Then** a LLM-as-Judge evaluator is implemented in service_backend/evals/judges/response_quality.py with rubrics for: response relevance (does the answer address the question?), factual accuracy (is the answer consistent with the knowledge base?) (FR-73)
**And** a DeepEval test suite is configured in service_backend/evals/deepeval/ with metrics: Faithfulness, AnswerRelevancy, Hallucination (FR-74)
**And** a fixture dataset of 20 golden Q&A pairs covering balance, plan, recharge, dispute, and FAQ queries is stored in service_backend/evals/fixtures/chatbot_golden.json
**And** the harness can run against any LangGraph graph by accepting a graph_callable and fixture set
**And** target thresholds are enforced: LLM-as-Judge ≥ 80% pass rate (NFR-11), Hallucination < 5% (NFR-12)
**And** eval results are written to a JSON report; CI fails if thresholds are not met

---

### Story 5.3: RAG Pipeline — Milvus Hybrid Search

As a **subscriber**,
I want the chatbot to answer general telecom FAQs and plan/billing questions by retrieving from a structured knowledge base,
So that I get accurate, grounded answers rather than hallucinated responses.

**Acceptance Criteria:**

**Given** a subscriber sends a query to the chatbot
**When** the Support Agent determines a RAG lookup is needed
**Then** the query is embedded using text-embedding-3-small (1536 dims) via Azure OpenAI (FR-26)
**And** a hybrid search is performed: HNSW vector search on faq_chunks/plan_vectors + BM25 keyword search, results re-ranked by RRF (ARCH-8)
**And** the top-3 retrieved chunks are included in the LLM prompt as grounding context
**And** the retrieval trace (query embedding, top-k results, RRF scores) is logged to LangFuse as a retrieval span (FR-72)
**And** if no relevant chunk is found (all scores below threshold), the agent responds: "I don't have information on that. Would you like to speak to a support agent?"

---

### Story 5.4: CopilotKit Runtime & Support Agent Graph

As a **subscriber**,
I want to query my balance and plan details, get FAQ answers, and maintain conversational context across turns through the chatbot,
So that I can resolve my queries without navigating multiple screens.

**Acceptance Criteria:**

**Given** the CopilotKit runtime is wired as a FastAPI router at POST /api/chat/stream (ARCH-13)
**When** a subscriber sends a message
**Then** the LangGraph Support Agent graph processes the message with AG-UI streaming protocol
**And** the agent has access to tools: get_balance (reads Valkey `balance:{msisdn}`), get_plan (DB query), get_usage, rag_search (Story 5.3) (FR-22, FR-23, FR-26)
**And** conversational context (last 10 turns) is stored and retrieved from Valkey HASH `chat_context:{session_id}` with 2h TTL (FR-25, ARCH-5)
**And** useCopilotReadable hooks expose balance, active plan, and session context to the agent graph so it can answer without extra API calls (ARCH-23)
**And** every agent node execution is traced to LangFuse with: node name, input, output, model (GPT-5.4-mini), token usage, latency (FR-72)
**And** the chatbot response streams token-by-token to the frontend via AG-UI SSE

---

### Story 5.5: Input Validation Guardrails

As a **platform engineer**,
I want the chatbot to reject malformed, adversarial, or suspicious inputs before they reach the LLM,
So that the system is protected from prompt injection and abuse.

**Acceptance Criteria:**

**Given** a subscriber sends a message to the chatbot
**When** the guardrail middleware processes it
**Then** messages exceeding 2,000 characters are rejected with: "Your message is too long. Please keep it under 2,000 characters." (FR-27)
**And** messages containing prompt injection patterns (e.g., "ignore previous instructions", "system:") are rejected with: "I can only help with billing and account queries."
**And** messages with no semantic overlap with telecom/billing topics (cosine similarity < 0.2 against a topic seed embedding) are rejected with: "I'm a billing assistant and can only help with account and plan queries."
**And** all rejected messages are logged to an audit table (guardrail_rejections) with: session_id, rejection_reason, message_hash (not raw content for PII safety) (ARCH-32)

---

### Story 5.6: Recharge via Chatbot & Multi-Agent Tool Calls

As a **subscriber**,
I want to initiate and complete a recharge through the chatbot,
So that I don't have to leave the conversation to top up my account.

**Acceptance Criteria:**

**Given** a subscriber asks the chatbot to "recharge" or "top up"
**When** the Support Agent detects the recharge intent
**Then** it calls the list_plans tool and presents top 3 recommended plans as plan cards in the chat UI (FR-24)
**And** on subscriber selection, it calls the initiate_recharge tool which POSTs to /api/v1/subscriber/recharge with the subscriber's default payment method
**And** on success, the chatbot responds with: "Your ₹{X} recharge is complete. New balance: ₹{Y}. Receipt: {receipt_url}"
**And** the recharge tool call and response are traced to LangFuse as a tool span (FR-72)

**Given** the subscriber has no saved payment method
**When** the recharge intent is detected
**Then** the agent responds: "You don't have a saved payment method. Please add one at Settings > Payment Methods."

---

### Story 5.7: Rating Agent — Charge Breakdown Explanation

As a **subscriber**,
I want to ask the chatbot why I was charged a specific amount and get a detailed breakdown,
So that I can understand my bill and dispute it if needed.

**Acceptance Criteria:**

**Given** a subscriber asks "why was I charged X on [date]?"
**When** the Support Agent identifies the charge breakdown intent
**Then** it invokes the Rating Agent (A2A) via LangGraph node with the CDR reference and subscriber_id (FR-29)
**And** the Rating Agent queries billing_audit_log for the CDR, fetches the plan's rate for that event type (voice/data/SMS), and returns: cdr_id, event_type, duration_or_data, rate_per_unit, charge_paise, balance_before, balance_after
**And** the Support Agent presents the breakdown as a collapsible table in the chat UI
**And** both the Support Agent → Rating Agent call and Rating Agent response are traced as child spans in LangFuse (FR-72)

---

### Story 5.8: Dispute Workflow & Balance Management Agent

As a **subscriber**,
I want to raise a billing dispute via the chatbot and have a support ticket auto-created with pre-filled details,
So that I don't have to repeat information and I have a ticket ID to track my case.

**Acceptance Criteria:**

**Given** a subscriber says "I want to dispute a charge" or "this charge is wrong"
**When** the Support Agent detects the dispute intent
**Then** it asks for the CDR reference (or date) to identify the charge, fetches the breakdown via the Rating Agent (Story 5.7), and presents it for confirmation (FR-30)
**And** on subscriber confirmation, it calls POST /api/v1/support/tickets with pre-filled: subscriber_id, cdr_reference, charge_paise, dispute_reason = "subscriber_initiated", status = OPEN
**And** the chatbot responds: "Ticket #{ticket_id} has been created. Our team will review it within 48 hours."
**And** GET /api/v1/support/tickets lists the subscriber's open tickets with status and created_at (FR-28)

**Given** a subscriber asks "what's my wallet balance?" in chat
**When** the Support Agent detects a wallet query
**Then** it invokes the Balance Management Agent (A2A) which reads `balance:{msisdn}` from Valkey and returns the current balance in paise (FR-31)
**And** the A2A call is traced as a child span in LangFuse (FR-72)
**And** a Flyway migration creates: support_tickets table (ticket_id UUIDv7, subscriber_id, cdr_reference, dispute_reason, status, created_at, resolved_at)

---

### Story 5.9: Plan Recommendation Tool & Feedback Loop

As a **subscriber**,
I want the chatbot to recommend the best plan for me based on my usage patterns and accept or dismiss the recommendation,
So that I make informed recharge decisions tailored to my actual behaviour.

**Acceptance Criteria:**

**Given** a subscriber asks for a plan recommendation or the agent determines one is useful
**When** the plan recommendation tool is invoked
**Then** it performs hybrid search on plan_vectors using: subscriber's 30-day CDR usage profile as the query embedding, filtered by price range tolerance ±20% of last recharge (FR-32)
**And** top 2 plans are returned with a natural-language rationale: "Based on your {X}GB data usage this month, the {Plan Name} gives you more data at ₹{Y}."
**And** the plans are displayed as Accept/Dismiss cards in the chat UI (FR-33)

**Given** a subscriber clicks Accept
**When** the feedback is logged
**Then** POST /api/v1/recommendations/feedback records: subscriber_id, plan_id, action = ACCEPTED, session_id, timestamp (FR-33)
**And** if dismissed, action = DISMISSED is logged instead

---

### Story 5.10: Conclusion Agent & Notification Agent (Session End)

As a **subscriber**,
I want to receive a relevant follow-up notification after my chat session if the agent determines one is warranted,
So that I'm reminded of actions I didn't complete or offers I might want to act on.

**Acceptance Criteria:**

**Given** a chatbot session ends (user closes chat or 2h TTL expires on chat_context)
**When** the Conclusion Agent runs
**Then** it reads the session history from Valkey HASH `chat_context:{session_id}`, summarises key learnings (topics discussed, actions taken, unresolved queries), and stores them in the session_learnings table (FR-34)
**And** it triggers the Notification Agent (A2A) with the session summary (FR-34)

**Given** the Notification Agent receives the session summary
**When** it evaluates whether to send a notification
**Then** it uses GPT-5.4-mini to decide: should a notification be sent? (yes/no), notification type (RECHARGE_REMINDER | PLAN_SUGGESTION | DISPUTE_FOLLOWUP | NONE), channel (push/SMS), and when (now / +1h / +24h) (FR-35)
**And** if the decision is to send, a notification event is published to notification.events with the decision payload
**And** the Notification Agent decision and output are traced to LangFuse (FR-72)
**And** a Flyway migration creates: session_learnings table (session_id, subscriber_id, summary_text, created_at)

---

## Epic 6: Fraud Detection (TDD-first)

The fraud management team can monitor real-time CDR anomalies, review AI-escalated fraud cases, and act on SIM swap and suspicious recharge alerts. Confirmed fraud triggers automatic account protection. Eval harness is written first.

---

### Story 6.1: Eval Harness — Fraud Detection Agent Accuracy

As a **QA engineer**,
I want a fraud detection evaluation harness with a golden fixture set before any fraud agent code is written,
So that fraud agent implementations can be validated against accuracy targets from day one.

**Acceptance Criteria:**

**Given** the fraud eval harness is set up
**When** `just test` runs the eval suite
**Then** a fixture dataset of 50 CDR sequences is stored in service_backend/evals/fixtures/fraud_golden.json: 25 true-positive fraud cases (SIM swap, velocity abuse, suspicious recharge), 25 true-negative clean cases
**And** an evaluator asserts that the Fraud Detection Agent correctly classifies each case as: confirmed_fraud | false_positive | needs_review
**And** the target true-positive rate ≥ 75% is enforced as a CI gate (NFR-13)
**And** a LangFuse trace template is defined for fraud agent calls: node name, input (7-day CDR summary), output (verdict), model, confidence_score
**And** the harness accepts any LangGraph fraud graph callable and runs against the fixture set

---

### Story 6.2: Rule-Based CDR Pre-Screener

As a **platform engineer**,
I want every CDR event on cdr.enriched.filtered to be evaluated against a set of anomaly rules before reaching the Fraud Detection Agent,
So that only genuinely suspicious events are escalated to the expensive LLM-powered agent.

**Acceptance Criteria:**

**Given** a CDR event is published to cdr.enriched.filtered
**When** the rule-based pre-screener processes it
**Then** it evaluates the event against 4 rule types: velocity (>50 CDRs in 1 hour for a single MSISDN), geographic anomaly (roaming event within 30 minutes of a domestic call), SIM swap flag (sim_swap_flag=true in subscriber record), suspicious recharge (>3 recharges in 24 hours) (FR-60)
**And** events matching any rule have fraud_signal = true appended to the event and are published to cdr.fraud.flagged (ARCH-10)
**And** events with no match are forwarded to cdr.enriched.filtered consumer without escalation
**And** rule thresholds (velocity limit, recharge count) are read from DB config records (not hardcoded)
**And** a Flyway migration creates: fraud_rules table (rule_id, rule_type, threshold_value, is_active), fraud_events table (event_id UUIDv7, cdr_id, msisdn, rule_triggered, detected_at)

---

### Story 6.3: Fraud Detection Agent — LLM-Powered Risk Analysis

As a **fraud analyst**,
I want flagged CDR events to be analysed by a LangGraph-powered Fraud Detection Agent using 7-day subscriber history,
So that genuine fraud is distinguished from false positives before entering the case queue.

**Acceptance Criteria:**

**Given** an event is published to cdr.fraud.flagged
**When** the Fraud Detection Agent processes it (asynchronously — never in the balance deduction hot path) (ARCH-14, FR-61)
**Then** the agent fetches the subscriber's last 7 days of CDR history from Postgres
**And** it invokes GPT-5.4 with a structured prompt containing: rule triggered, CDR pattern, subscriber history summary, and outputs a verdict: confirmed_fraud | false_positive | needs_review with a confidence_score (0.0–1.0)
**And** the agent is implemented as a LangGraph async graph in service_backend/agents/fraud/graph.py
**And** the full agent run is traced to LangFuse: input (CDR event + history), output (verdict), model, token usage, latency (FR-72)

**Given** the verdict is confirmed_fraud or needs_review
**When** the agent completes
**Then** a fraud_cases row is inserted with: case_id (UUIDv7), msisdn, verdict, confidence_score, rule_triggered, agent_trace_id, status = OPEN (FR-62)
**And** a fraud.alerts event is published with the case summary (FR-62)

**Given** the verdict is false_positive
**When** the agent completes
**Then** the fraud_events row is marked as resolved = false_positive; no fraud_cases row is created

---

### Story 6.4: Real-Time Anomaly Feed & Fraud Case Queue UI

As a **fraud analyst**,
I want a live dashboard showing flagged CDR anomalies and a case queue for AI-escalated fraud cases,
So that I can monitor threats in real time and manage investigations efficiently.

**Acceptance Criteria:**

**Given** a fraud analyst logs in with role = 'fraud' and navigates to /fraud/dashboard
**When** the page loads
**Then** the AnomalyFeed.tsx component connects to ws://localhost:8000/ws/fraud/alerts and displays a live-updating list: MSISDN[-4:], rule triggered, detected_at, confidence_score (FR-53, ARCH-21)
**And** new alerts appear at the top of the feed without a page reload; feed auto-scrolls to latest

**Given** confirmed_fraud or needs_review cases exist in fraud_cases
**When** the analyst views /fraud/cases
**Then** GET /api/v1/fraud/cases returns a paginated list: case_id, MSISDN[-4:], verdict, confidence_score, status, detected_at (FR-54)
**And** the analyst can update a case status: OPEN → UNDER_REVIEW → RESOLVED with a free-text notes field
**And** PATCH /api/v1/fraud/cases/{case_id} accepts: status, analyst_notes, resolved_by

---

### Story 6.5: SIM Swap & Suspicious Recharge Alerts

As a **fraud analyst**,
I want dedicated alert views for SIM swap patterns and suspicious recharge frequency,
So that high-priority account takeover risks are immediately visible and distinguishable from other fraud types.

**Acceptance Criteria:**

**Given** the Fraud Detection Agent confirms a SIM swap pattern (rule_triggered = SIM_SWAP)
**When** the fraud.alerts event is consumed by the UI WebSocket
**Then** the alert appears in the AnomalyFeed with a red "SIM SWAP" badge (FR-55)
**And** a dedicated filter on /fraud/cases?type=SIM_SWAP shows only SIM swap escalations

**Given** the pre-screener detects >3 recharges in 24 hours for a subscriber
**When** the fraud agent confirms suspicious recharge pattern
**Then** the alert appears with an amber "RECHARGE ANOMALY" badge (FR-56)
**And** the case detail view shows the recharge timestamps and amounts

---

### Story 6.6: Account Takeover Prevention — Blacklist, Cognito Disable & JWT Revocation

As a **platform engineer**,
I want confirmed SIM swap fraud to automatically blacklist the subscriber, disable their Cognito account, and revoke active JWTs,
So that a compromised account is locked down immediately without manual intervention.

**Acceptance Criteria:**

**Given** the Fraud Detection Agent verdict = confirmed_fraud AND rule_triggered = SIM_SWAP
**When** the account protection workflow runs
**Then** a row is inserted into fraud_blacklist: subscriber_id, msisdn, blacklisted_at, reason = 'SIM_SWAP_CONFIRMED', blacklisted_by = 'fraud_agent' (FR-66, ARCH-33)
**And** the MiniStack Cognito admin API is called to disable the subscriber's user account (ARCH-33)
**And** all the subscriber's active tokens are revoked via the Cognito admin API (token revocation) — JWTs are stateless, so there is no `auth_sessions` table; the 30-minute access-token TTL bounds the residual validity window (architecture §1.8.1/§1.8.2, ARCH-33)
**And** subsequent JWT validation for this subscriber returns HTTP 401 — the FastAPI JWT middleware checks fraud_blacklist on every request for subscribers with active fraud cases
**And** the account protection actions are recorded in audit_log with event_type = 'ACCOUNT_TAKEOVER_PREVENTION'
**And** a Flyway migration creates: fraud_blacklist table (blacklist_id UUIDv7, subscriber_id, msisdn, blacklisted_at, reason, blacklisted_by)

---

## Epic 7: Ops & Marketing Dashboard (TDD-first)

Operations can monitor plan stock and order fulfilment. Marketing can forecast subscriber growth, build targeted upsell segments with LLM labelling, and receive strategy recommendations. Engineering can diagnose billing issues via the Root Cause Analysis Agent. Eval harness is written first.

---

### Story 7.1: Eval Harness — ML Forecast & Upsell Quality

As a **QA engineer**,
I want evaluation harnesses for the ML forecasting model and LLM upsell strategy agent before any implementation,
So that accuracy and quality targets are enforced from the first story.

**Acceptance Criteria:**

**Given** the ops eval harness is set up
**When** `just test` runs the eval suite
**Then** a ML forecast evaluator loads a fixture CSV of 6-month historical activation data and asserts that the trained scikit-learn model achieves MAPE < 15% on a 3-month holdout set (NFR-14)
**And** a LLM-as-Judge evaluator for upsell strategy text asserts: strategy is specific to the segment (not generic), actionable (contains at least one concrete offer), and appropriately scoped (no hallucinated product names) (FR-73)
**And** both evaluators return structured pass/fail results and CI fails if targets are not met
**And** fixture files are stored in service_backend/evals/fixtures/: forecast_historical.csv, upsell_golden_segments.json

---

### Story 7.2: Plan Stock Dashboard & Order Fulfilment View

As an **operations team member**,
I want to see real-time subscriber counts per active plan and a live view of subscriber orders across all fulfilment states,
So that I can monitor plan adoption and identify stalled activations.

**Acceptance Criteria:**

**Given** an operator logs in with role = 'ops' and navigates to /ops/dashboard
**When** the page loads
**Then** GET /api/v1/ops/plan-stock returns: plan_id, plan_name, subscriber_count, sorted by subscriber_count descending (FR-42)
**And** the PlanStock.tsx table is sortable by plan name and subscriber count; clicking a row filters the order fulfilment view

**Given** the operator views the order fulfilment panel
**When** GET /api/v1/ops/orders is called
**Then** it returns subscriber orders grouped by status: CREATED, KYC_PENDING, KYC_VERIFIED, ACTIVATED with count per group (FR-43)
**And** the OrderFulfilment.tsx displays a status board with counts and a paginated list of orders for the selected status group
**And** both endpoints use queries.py (SELECT only) per CQRS rules (ARCH-4)

---

### Story 7.3: Subscriber Growth Forecast (ML, 3-Month)

As an **operations team member**,
I want a 3-month subscriber activation and churn forecast with confidence intervals,
So that I can plan network capacity and staffing ahead of demand.

**Acceptance Criteria:**

**Given** at least 90 days of historical activation data exists in Postgres
**When** GET /api/v1/ops/forecasts/subscriber-growth is called
**Then** the endpoint trains (or loads cached) a scikit-learn time-series model on daily activation and churn counts (FR-44)
**And** returns a 90-day projection: date, predicted_activations, predicted_churn, lower_bound, upper_bound (95% CI)
**And** MAPE < 15% on the most recent 30-day holdout period (NFR-14)
**And** the Forecasts.tsx chart renders the projection as a line chart with shaded confidence interval band (Recharts)
**And** the model is retrained daily via a scheduled job; results are cached in Postgres (forecast_results table)

---

### Story 7.4: Plan Demand Forecast (30–90 Day)

As a **marketing team member**,
I want a 30 to 90-day demand forecast per plan so I can identify which plans to promote,
So that marketing spend targets high-growth segments.

**Acceptance Criteria:**

**Given** GET /api/v1/ops/forecasts/plan-demand is called
**When** the response is returned
**Then** it returns per-plan projections: plan_id, plan_name, predicted_uptake_30d, predicted_uptake_60d, predicted_uptake_90d (FR-45)
**And** predictions are computed using a per-plan scikit-learn model trained on the last 90 days of recharge events
**And** the Forecasts.tsx page has a "Plan Demand" tab showing a sortable table of per-plan predictions with a sparkline trend chart per row

---

### Story 7.5: Target Base Builder — Dynamic KPI Filter

As a **marketing team member**,
I want to define a subscriber candidate pool by applying composable filter criteria on KPIs from a materialised view,
So that I can precisely target the right subscribers for an upsell campaign.

**Acceptance Criteria:**

**Given** a marketer navigates to /ops/segmentation
**When** the Target Base Builder loads
**Then** GET /api/v1/ops/segmentation/kpi-schema returns the column names and types from the segmentation_subscriber_kpi_r_mvw materialised view (FR-46)
**And** the UI renders a dynamic filter builder: each filter row is a KPI column + operator (>, <, =, BETWEEN) + value; rows are combinable with AND
**And** POST /api/v1/ops/segmentation/preview applies the filters and returns: total_count, sample of 10 subscriber rows (MSISDN[-4:] only), min/max/mean for each numeric KPI (FR-47)
**And** the Segmentation.tsx component uses React Query to debounce filter changes and re-fetch the preview on each change
**And** a Flyway migration creates: segmentation_subscriber_kpi_r_mvw materialised view joining subscribers, wallet_balance, cdr events (90-day aggregates), plan data

---

### Story 7.6: LLM Segment Labelling & Rule Induction Agent

As a **marketing team member**,
I want the system to send pre-aggregated subscriber feature vectors to an LLM for descriptive segment labels, then have a Rule Induction Agent generalise those labels into reusable KPI-predicate rules,
So that I have interpretable, scalable segment definitions I can apply without re-running LLM inference.

**Acceptance Criteria:**

**Given** a marketer clicks "Generate Segment Labels" on a filtered pool
**When** the labelling job runs
**Then** up to 100 sampled subscribers' pre-aggregated feature vectors (not raw PII) are sent to GPT-5.4-mini in a single prompt batch (FR-48, NFR-8)
**And** each subscriber receives a descriptive label: e.g., "Heavy data user, plan-loyal, low churn risk"
**And** labels are stored in subscriber_segment_labels table: subscriber_id, label_text, session_id, created_at

**Given** labels are generated for a pool
**When** the marketer clicks "Induce Rules"
**Then** the Rule Induction Agent (LangGraph) reads all labels and KPI values for the pool, infers 3–5 KPI-predicate rules that explain the label clusters, and persists them to segment_rules table (FR-49)
**And** example rule format: `{rule_id, description: "data_gb_30d > 8 AND plan_price_paise < 50000", predicates: [...]}` 
**And** the Rule Induction Agent run is traced to LangFuse (FR-72)
**And** a Flyway migration creates: subscriber_segment_labels, segment_rules tables

---

### Story 7.7: Segment Classification at Scale & Upsell Strategy Agent

As a **marketing team member**,
I want saved segment rules applied deterministically to the full subscriber base and an LLM agent to generate a targeted upsell strategy per segment,
So that I have actionable campaign playbooks without re-calling the LLM for every subscriber.

**Acceptance Criteria:**

**Given** segment rules exist in segment_rules table
**When** the marketer clicks "Classify All"
**Then** POST /api/v1/ops/segmentation/classify applies each rule's predicates against all subscribers in the filtered pool via a Postgres query (no LLM call) (FR-50)
**And** each subscriber is assigned a segment_rule_id; results written to subscriber_segment_classifications table
**And** per-segment statistics are returned: segment label, rule description, subscriber_count, mean KPI values

**Given** segment classifications exist
**When** the marketer clicks "Generate Upsell Strategy" for a segment
**Then** the Upsell Strategy Agent (LangGraph) receives: segment label, rule predicates, mean KPIs, and top 3 available plans by price (FR-51)
**And** it returns a 3–5 sentence textual strategy: which plans to promote, why they fit this segment, suggested messaging angle
**And** the strategy is displayed in the Segmentation.tsx UI and stored in upsell_strategies table (strategy_id, segment_rule_id, strategy_text, created_at)
**And** the Upsell Strategy Agent run is traced to LangFuse (FR-72)
**And** a Flyway migration creates: subscriber_segment_classifications, upsell_strategies tables

---

### Story 7.8: Ops Observability Dashboard — CDR Monitor & Pipeline Health

As an **operations team member**,
I want to monitor CDR processing health, pipeline latency, and notification delivery status from a single dashboard,
So that I can identify and respond to degraded billing performance before subscribers are impacted.

**Acceptance Criteria:**

**Given** an operator navigates to /ops/health
**When** the page loads
**Then** GET /api/v1/ops/pipeline-health returns: cdr_events_last_5m (count), p95_balance_latency_ms, p99_balance_latency_ms, error_rate_pct (failed / total CDRs in last 5 min), dlq_depth (FR-52)
**And** a green/amber/red SLA indicator is shown: green if p95 ≤ 200ms, amber if 200–500ms, red if >500ms (NFR-1)
**And** GET /api/v1/ops/notification-health returns: notifications_sent_last_1h, simulated_success_pct, failed_count grouped by notification_type
**And** the OpsHealth.tsx page auto-refreshes every 30 seconds via React Query

---

### Story 7.9: Root Cause Analysis Agent

As an **engineering team member**,
I want an LLM-powered Root Cause Analysis Agent that can diagnose billing discrepancies and failed recharges by querying audit logs, CDR data, and SOP knowledge base,
So that I can resolve customer-reported billing issues quickly without manual SQL investigation.

**Acceptance Criteria:**

**Given** an engineer navigates to /ops/rca and enters an investigation prompt (e.g., "Why was subscriber MSISDN[-4:] charged twice on [date]?")
**When** POST /api/v1/ops/rca is called
**Then** the RCA Agent (LangGraph) is invoked with the prompt as input (FR-75)
**And** the agent has access to tools: query_audit_log (SELECT from billing_audit_log by subscriber/date), query_cdrs (SELECT from cdr events), rag_search_sop (search sop_chunks in Milvus for relevant billing SOPs)
**And** it returns a structured investigation report: root_cause (text), supporting_evidence (list of audit rows + SOP references), recommended_action
**And** the RCA Agent run is traced to LangFuse with all tool calls as child spans (FR-72)
**And** the report is displayed in the OpsHealth.tsx RCA tab and stored in rca_investigations table (investigation_id UUIDv7, prompt, report_json, created_at, engineer_id)
**And** a Flyway migration creates: rca_investigations table
