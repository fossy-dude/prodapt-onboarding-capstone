# MVP
```mermaid
architecture-beta

    %% ── USERS ────────────────────────────────────────────────────────
    group users(cloud)["Users"]
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
    service auth(server)["Identity Provider (AWS Cognito)"]

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
    service llm(logos:azure)["LLM Provider (Azure OpenAI GPT-4o-mini)"]

    %% ── OBSERVABILITY ───────────────────────────────────────────────
    group observability(logos:grafana-icon)["Observability (Docker)"]
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

# Target State
```mermaid
architecture-beta

    %% ── USERS ────────────────────────────────────────────────────────
    group users(internet)[Users – Global]
        service subscriber(server)[Subscriber]      in users
        service ops_user(server)[Ops Manager]       in users
        service fraud_user(server)[Fraud Analyst]   in users
        service sim_user(server)[Simulator / Dev]   in users

    %% ── CDN + API EDGE ───────────────────────────────────────────────
    service cloudfront(aws:cloudfront)[CDN
_(AWS CloudFront)_]
    service s3_fe(aws:s3)[Static Assets
_(Amazon S3 – ap-south-1)_]
    service api_gateway(aws:api-gateway)[API Gateway
_(AWS API Gateway + ALB
JWT validate · Rate limit FR-36)_]

    %% ── AUTH (Keycloak on EKS) ───────────────────────────────────────
    service keycloak(server)[Identity Provider
_(Keycloak – EKS
Enterprise RBAC · OTP)_]

    %% ── AWS EKS CLUSTER ──────────────────────────────────────────────
    group eks(aws:eks)[AWS EKS – ap-south-1
_(Kubernetes Microservices)_]

        %% Application microservices
        service svc_acct(logos:python)[Account Service
_(Python/FastAPI – FR-1–7)_]        in eks
        service svc_bal(logos:python)[Balance Service
_(Python/FastAPI – FR-8–11)_]       in eks
        service svc_rchg(logos:python)[Recharge Service
_(Python/FastAPI – FR-12–17)_]      in eks
        service svc_notif(logos:python)[Notification Service
_(Python/FastAPI – FR-18–21)_]      in eks
        service svc_chat(logos:python)[Chatbot Service
_(Python/FastAPI + LangGraph
FR-22–36)_]                         in eks
        service svc_ussd(logos:python)[USSD Service
_(Python/FastAPI – FR-37–41)_]      in eks
        service svc_ops(logos:python)[Ops Service
_(Python/FastAPI – FR-42–52)_]      in eks
        service svc_fraud(logos:python)[Fraud Service
_(Python/FastAPI + LangGraph
FR-53–56 · FR-60–62)_]             in eks
        service svc_sim(logos:rust)[Simulator Service
_(Rust – CDR Generator
FR-68–70)_]                         in eks
        service svc_eval(logos:python)[Eval Service
_(Python – DeepEval · LLM-Judge
FR-72–77)_]                         in eks

        %% CDR Ingestion (Rust)
        service rust_consumer(logos:rust)[CDR Ingestion Service
_(Rust · tokio + rdkafka
100K eps · micro-batch=500)_]       in eks
        service dedup(disk)[Idempotency Guard
_(Valkey SET · TTL 24h)_]           in eks
        service bal_write(server)[Balance Writer
_(INCRBY → async RDS flush)_]       in eks
        service fraud_screen(server)[Rule Pre-Screener
_(Deterministic)_]                  in eks
        service dlq_h(server)[DLQ Handler
_(cdr.dlq)_]                        in eks

        %% LangGraph Agents
        service chatbot_a(logos:openai)[Self-Care Chatbot
_(LangGraph – Support · Rating
Balance · Conclusion · Notif)_]    in eks
        service fraud_a(logos:openai)[Fraud Detection Agent
_(LangGraph – Rule + LLM)_]        in eks
        service ops_a(logos:openai)[Ops/Marketing Agents
_(LangGraph – Segment/Upsell/RCA)_] in eks

        %% Platform services on EKS
        service milvus_d(database)[Vector Store
_(Milvus Distributed
Query + Data Nodes)_]               in eks
        service langfuse_eks(logos:openai)[Agent Traces
_(LangFuse – EKS · scaled)_]       in eks
        service fluentd_ds(logos:fluentd)[Log Routing
_(Fluentd DaemonSet)_]              in eks

    %% ── MANAGED AWS DATA SERVICES ────────────────────────────────────
    group aws_data(aws)[Managed Data Services – AWS ap-south-1]
        service msk(aws:msk)[Event Bus
_(Amazon MSK / Kafka
24 partitions)_]                    in aws_data
        service t_raw(server)[cdr.raw
_(24p)_]                            in aws_data
        service t_enr(server)[cdr.enriched.filtered
_(24p)_]                            in aws_data
        service t_fraud_f(server)[cdr.fraud.flagged
_(6p)_]                             in aws_data
        service t_fraud_a(server)[fraud.alerts
_(6p)_]                             in aws_data
        service t_notif(server)[notification.events
_(12p)_]                            in aws_data
        service t_dlq(server)[cdr.dlq
_(6p)_]                             in aws_data
        service rds(aws:rds)[Primary Database
_(Amazon RDS PostgreSQL
Multi-AZ)_]                         in aws_data
        service elasticache(aws:elasticache)[Cache & Write Buffer
_(Amazon ElastiCache Valkey
noeviction)_]                       in aws_data
        service s3_audit(aws:s3)[Audit Archive
_(Amazon S3 + S3 Glacier
6-yr TRAI retention)_]              in aws_data
        service secrets(aws:secrets-manager)[Secrets Management
_(AWS Secrets Manager)_]            in aws_data

    %% ── LLM PROVIDER ─────────────────────────────────────────────────
    service llm(logos:microsoft-azure)[LLM Provider
_(Azure OpenAI – GPT-5.4
text-embedding-3-small)_]

    %% ── OBSERVABILITY – LGTM ─────────────────────────────────────────
    group lgtm(logos:grafana)[Observability Stack – AWS ap-south-1]
        service tempo(logos:grafana)[Distributed Traces
_(Grafana Tempo)_]                  in lgtm
        service mimir(logos:grafana)[Metrics
_(Grafana Mimir)_]                  in lgtm
        service loki(logos:grafana)[Logs
_(Grafana Loki)_]                   in lgtm
        service grafana_ui(logos:grafana)[Dashboards
_(Grafana)_]                        in lgtm

    %% ── IaC / CI-CD ──────────────────────────────────────────────────
    service terraform(logos:terraform)[Infrastructure as Code
_(Terraform – AWS ap-south-1
VPC · EKS · RDS · MSK · ElastiCache
Cognito · S3 · CloudFront · API GW)_]
    service cicd(logos:github-actions)[CI/CD
_(GitHub Actions – uv tox
Rust build · Helm deploy)_]

    %% ── EDGES ────────────────────────────────────────────────────────
    %% Users → Edge
    subscriber:R --> L:cloudfront
    ops_user:R --> L:cloudfront
    fraud_user:R --> L:cloudfront
    sim_user:R --> L:cloudfront

    cloudfront:R --> L:s3_fe
    cloudfront:B --> T:api_gateway
    api_gateway:R --> L:keycloak
    api_gateway:B --> T:eks{group}

    %% Agent wiring
    svc_chat:R --> L:chatbot_a
    svc_fraud:R --> L:fraud_a
    svc_ops:R --> L:ops_a
    chatbot_a:R --> L:llm
    fraud_a:R --> L:llm
    ops_a:R --> L:llm
    chatbot_a:B --> T:milvus_d
    ops_a:B --> T:milvus_d

    %% CDR ingest pipeline
    t_raw:R --> L:rust_consumer
    rust_consumer:R --> L:dedup
    dedup:R --> L:elasticache
    rust_consumer:B --> T:bal_write
    bal_write:B --> T:elasticache
    bal_write:R --> L:rds
    rust_consumer:B --> T:fraud_screen
    fraud_screen:R --> L:t_fraud_f
    fraud_screen:B --> T:t_enr
    rust_consumer:B --> T:dlq_h
    dlq_h:R --> L:t_dlq

    %% Topic consumers
    t_enr:R --> L:svc_notif
    t_fraud_f:R --> L:fraud_a
    t_fraud_a:R --> L:svc_fraud
    t_notif:R --> L:svc_notif

    %% Publish to topics
    svc_sim:R --> L:t_raw
    chatbot_a:B --> T:t_notif
    fraud_a:B --> T:t_fraud_a

    %% Services → Data stores
    svc_acct:B --> T:rds
    svc_bal:B --> T:elasticache
    svc_rchg:B --> T:rds
    svc_rchg:B --> T:elasticache
    svc_ussd:B --> T:elasticache
    svc_ops:B --> T:rds
    rds:B --> T:s3_audit
    secrets:R --> L:eks{group}

    %% Observability
    eks{group}:R --> L:tempo
    eks{group}:R --> L:mimir
    fluentd_ds:R --> L:loki
    chatbot_a:B --> T:langfuse_eks
    fraud_a:B --> T:langfuse_eks
    ops_a:B --> T:langfuse_eks
    tempo:B --> T:grafana_ui
    mimir:B --> T:grafana_ui
    loki:B --> T:grafana_ui

    %% IaC / CI-CD
    terraform:B --> T:aws_data{group}
    cicd:B --> T:eks{group}
    cicd:B --> T:s3_fe
```