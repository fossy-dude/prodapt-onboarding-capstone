```mermaid
architecture-beta

    %% ── USERS ────────────────────────────────────────────────────────
    group users(internet)["Users"]
        service subscriber(server)["Subscriber Portal"] in users
        service ops_user(server)["Ops Dashboard"] in users
        service fraud_user(server)["Fraud Dashboard"] in users
        service sim_user(server)["Simulator / Dev"] in users

    %% ── FRONTEND ─────────────────────────────────────────────────────
    group frontend(logos:react)["Frontend (React 18 + Vite + TailwindCSS)"]
        service fe_sub(logos:react)["Subscriber Portal (React SPA)"] in frontend
        service fe_ops(logos:react)["Ops Dashboard (React SPA)"] in frontend
        service fe_fraud(logos:react)["Fraud Dashboard (React SPA)"] in frontend
        service fe_sim(logos:react)["Simulator Portal (React SPA)"] in frontend

    %% ── AUTH (MiniStack) ─────────────────────────────────────────────
    service auth(aws:cognito)["Identity Provider (AWS Cognito)"]

    %% ── APP BACKEND (FastAPI monorepo) ───────────────────────────────
    group app_backend(logos:python)["App Backend (Python 3.14 + FastAPI)"]
        service acct_router(server)["Account Router (FR-1 to 7)"] in app_backend
        service bal_router(server)["Balance Router (FR-8 to 11)"] in app_backend
        service rchg_router(server)["Recharge Router (FR-12 to 17)"] in app_backend
        service notif_router(server)["Notifications Router (FR-18 to 21)"] in app_backend
        service ussd_router(server)["USSD Router (FR-37 to 41)"] in app_backend
        service ops_router(server)["Ops Router (FR-42 to 52)"] in app_backend
        service fraud_router(server)["Fraud Router (FR-53 to 56)"] in app_backend
        service sim_router(server)["Simulator Router (FR-68 to 70)"] in app_backend
        service copilot(server)["AG-UI Runtime (CopilotKit)"] in app_backend
        service chatbot_agent(server)["Self-Care Chatbot (LangGraph)"] in app_backend
        service fraud_agent(server)["Fraud Detection Agent (LangGraph)"] in app_backend
        service ops_agents(server)["Ops and Marketing Agents (LangGraph)"] in app_backend
        service milvus_lite(database)["Vector Store (Milvus Lite)"] in app_backend
        service ml(logos:python)["ML Forecasting (scikit-learn)"] in app_backend
        service pdf(server)["PDF Receipts (WeasyPrint)"] in app_backend

    %% ── CDR PIPELINE (separate codebase) ────────────────────────────
    group cdr_pipeline(logos:python)["CDR Pipeline (Python + aiokafka)"]
        service consumer(server)["CDR Consumer (batch 500)"] in cdr_pipeline
        service dedup(disk)["Idempotency Guard (Valkey TTL 24h)"] in cdr_pipeline
        service bal_writer(server)["Balance Writer (INCRBY async PG flush)"] in cdr_pipeline
        service screener(server)["Rule-Based Pre-Screener (Fraud Flags)"] in cdr_pipeline
        service dlq_handler(server)["DLQ Handler (cdr.dlq)"] in cdr_pipeline
        service mgmt_api(server)["Management API (pause/resume/DLQ)"] in cdr_pipeline

    %% ── EVENT BUS (Redpanda) ────────────────────────────────────────
    group event_bus(server)["Event Bus (Redpanda - 24 partitions)"]
        service t_raw(server)["cdr.raw (24p)"] in event_bus
        service t_enr(server)["cdr.enriched.filtered (24p)"] in event_bus
        service t_fraud_f(server)["cdr.fraud.flagged (6p)"] in event_bus
        service t_fraud_a(server)["fraud.alerts (6p)"] in event_bus
        service t_notif(server)["notification.events (12p)"] in event_bus
        service t_dlq(server)["cdr.dlq (6p)"] in event_bus

    %% ── DATA STORES ──────────────────────────────────────────────────
    service postgres(logos:postgresql)["Primary Database (PostgreSQL 16)"]
    service valkey(logos:redis)["Cache and Write Buffer (Valkey 512MB)"]

    %% ── LLM PROVIDER ────────────────────────────────────────────────
    service llm(logos:microsoft-azure)["LLM Provider (Azure OpenAI GPT-4o-mini)"]

    %% ── OBSERVABILITY ───────────────────────────────────────────────
    group observability(logos:grafana)["Observability (Docker)"]
        service langfuse(server)["Agent Traces (LangFuse)"] in observability
        service otel_tui(server)["Infra Traces and Metrics (OTEL-TUI)"] in observability
        service fluentd(server)["Log Routing (Fluentd)"] in observability

    %% ── CI/CD ────────────────────────────────────────────────────────
    service cicd(logos:github-actions)["CI/CD (GitHub Actions - uv tox)"]

    %% ── EDGES ────────────────────────────────────────────────────────
    subscriber:R --> L:fe_sub
    ops_user:R --> L:fe_ops
    fraud_user:R --> L:fe_fraud
    sim_user:R --> L:fe_sim

    fe_sub:R --> L:auth
    fe_sub:B --> T:copilot
    fe_sub:B --> T:bal_router
    fe_sub:B --> T:rchg_router
    fe_ops:B --> T:ops_router
    fe_fraud:B --> T:fraud_router
    fe_sim:B --> T:sim_router

    auth:B --> T:app_backend{group}

    copilot:B --> T:chatbot_agent
    chatbot_agent:R --> L:llm
    fraud_agent:R --> L:llm
    ops_agents:R --> L:llm
    chatbot_agent:B --> T:milvus_lite

    sim_router:B --> T:t_raw
    t_raw:R --> L:consumer
    consumer:R --> L:dedup
    dedup:R --> L:valkey
    consumer:B --> T:bal_writer
    bal_writer:B --> T:valkey
    bal_writer:R --> L:postgres
    consumer:B --> T:screener
    screener:R --> L:t_fraud_f
    screener:B --> T:t_enr
    consumer:B --> T:dlq_handler
    dlq_handler:R --> L:t_dlq

    t_fraud_f:B --> T:fraud_agent
    t_enr:B --> T:notif_router
    t_fraud_a:R --> L:fraud_router
    t_notif:R --> L:notif_router
    fraud_agent:R --> L:t_fraud_a
    chatbot_agent:B --> T:t_notif

    app_backend{group}:B --> T:postgres
    bal_router:B --> T:valkey
    ussd_router:R --> L:valkey
    rchg_router:B --> T:valkey

    app_backend{group}:R --> L:otel_tui
    cdr_pipeline{group}:R --> L:otel_tui
    chatbot_agent:B --> T:langfuse
    fraud_agent:B --> T:langfuse
    ops_agents:B --> T:langfuse
    fluentd:R --> L:otel_tui

    cicd:B --> T:app_backend{group}
    cicd:B --> T:cdr_pipeline{group}
```
