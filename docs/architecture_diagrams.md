```mermaid
architecture-beta

    %% ── USERS ────────────────────────────────────────────────────────
    group users(internet)[Users]
        service subscriber(server)[Subscriber Portal]  in users
        service ops_user(server)[Ops Dashboard]        in users
        service fraud_user(server)[Fraud Dashboard]    in users
        service sim_user(server)[Simulator / Dev]      in users

    %% ── FRONTEND (Docker – Vite dev server) ──────────────────────────
    group frontend(logos:react)[Frontend
_(React 18 + Vite + TailwindCSS)_]
        service fe_sub(logos:react)[Subscriber Portal
_(React SPA)_]    in frontend
        service fe_ops(logos:react)[Ops Dashboard
_(React SPA)_]    in frontend
        service fe_fraud(logos:react)[Fraud Dashboard
_(React SPA)_]   in frontend
        service fe_sim(logos:react)[Simulator Portal
_(React SPA)_]   in frontend

    %% ── AUTH (MiniStack) ─────────────────────────────────────────────
    service auth(aws:cognito)[Identity Provider
_(AWS Cognito – MiniStack)_]

    %% ── APP BACKEND (FastAPI monorepo) ───────────────────────────────
    group app_backend(logos:python)[App Backend – Docker
_(Python 3.14 + FastAPI)_]
        service acct_router(server)[Account Router
_(FR-1–7)_]         in app_backend
        service bal_router(server)[Balance Router
_(FR-8–11)_]        in app_backend
        service rchg_router(server)[Recharge Router
_(FR-12–17)_]       in app_backend
        service notif_router(server)[Notifications Router
_(FR-18–21)_]       in app_backend
        service ussd_router(server)[USSD Router
_(FR-37–41)_]       in app_backend
        service ops_router(server)[Ops Router
_(FR-42–52)_]       in app_backend
        service fraud_router(server)[Fraud Router
_(FR-53–56)_]       in app_backend
        service sim_router(server)[Simulator Router
_(FR-68–70)_]       in app_backend
        service copilot(server)[AG-UI Runtime
_(CopilotKit)_]     in app_backend
        service chatbot_agent(logos:openai)[Self-Care Chatbot
_(LangGraph – Support/Rating
Balance/Conclusion/Notif)_] in app_backend
        service fraud_agent(logos:openai)[Fraud Detection Agent
_(LangGraph – Rule + LLM)_] in app_backend
        service ops_agents(logos:openai)[Ops/Marketing Agents
_(LangGraph – Segment/Upsell/RCA)_] in app_backend
        service milvus_lite(database)[Vector Store
_(Milvus Lite – embedded)_] in app_backend
        service ml(logos:python)[ML Forecasting
_(scikit-learn)_]   in app_backend
        service pdf(server)[PDF Receipts
_(WeasyPrint)_]     in app_backend

    %% ── CDR PIPELINE (separate codebase) ────────────────────────────
    group cdr_pipeline(logos:python)[CDR Pipeline – Docker
_(Python + aiokafka)_]
        service consumer(server)[CDR Consumer
_(batch=500)_]      in cdr_pipeline
        service dedup(disk)[Idempotency Guard
_(Valkey SET · TTL 24h)_] in cdr_pipeline
        service bal_writer(server)[Balance Writer
_(INCRBY → async PG flush)_] in cdr_pipeline
        service screener(server)[Rule-Based Pre-Screener
_(Fraud Flags)_]    in cdr_pipeline
        service dlq_handler(server)[DLQ Handler
_(cdr.dlq)_]        in cdr_pipeline
        service mgmt_api(server)[Management API
_(pause/resume/DLQ inspect)_] in cdr_pipeline

    %% ── EVENT BUS (Redpanda) ────────────────────────────────────────
    group event_bus(logos:redpanda)[Event Bus – Docker
_(Redpanda – Kafka-compatible · 24 partitions)_]
        service t_raw(server)[cdr.raw
_(24p)_]            in event_bus
        service t_enr(server)[cdr.enriched.filtered
_(24p)_]            in event_bus
        service t_fraud_f(server)[cdr.fraud.flagged
_(6p)_]             in event_bus
        service t_fraud_a(server)[fraud.alerts
_(6p)_]             in event_bus
        service t_notif(server)[notification.events
_(12p)_]            in event_bus
        service t_dlq(server)[cdr.dlq
_(6p)_]             in event_bus

    %% ── DATA STORES ──────────────────────────────────────────────────
    service postgres(logos:postgresql)[Primary Database
_(PostgreSQL 16 – Docker)_]
    service valkey(logos:redis)[Cache & Write Buffer
_(Valkey – Docker · maxmem 512MB)_]

    %% ── LLM PROVIDER ────────────────────────────────────────────────
    service llm(logos:microsoft-azure)[LLM Provider
_(Azure OpenAI – GPT-5.4-mini
text-embedding-3-small)_]

    %% ── OBSERVABILITY ───────────────────────────────────────────────
    group observability(logos:grafana)[Observability – Docker]
        service langfuse(logos:openai)[Agent Traces
_(LangFuse – self-hosted)_] in observability
        service otel_tui(server)[Infra Traces/Metrics/Logs
_(OTEL-TUI + OTEL Collector)_] in observability
        service fluentd(logos:fluentd)[Log Routing
_(Fluentd)_]        in observability

    %% ── CI/CD ────────────────────────────────────────────────────────
    service cicd(logos:github-actions)[CI/CD
_(GitHub Actions – uv tox
lint · test · Docker build)_]

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