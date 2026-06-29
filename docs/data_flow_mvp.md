# CDR Pipeline

## CDR data input flow
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
  ├─► Dedup ──► Valkey SET (cdr_id, TTL=24h)
  │
  ├─► Balance Update ──► Valkey INCRBY pipeline (atomic)
  │                         └─► Async flush → PostgreSQL (bulk upsert, 2s or 5K)
  │
  └─► Filter & Publish ──► Redpanda: cdr.enriched.filtered
                              ├─► Fraud Pre-Screener (Kafka consumer, same Python codebase)
                              └─► Notification Trigger (Kafka consumer, same Python codebase)
```

## Fraud screener

Rules:
1. velocity (>50 CDRs in 1 hour for a single MSISDN)
2. geographic anomaly (roaming event within 30 minutes of a domestic call)
3. SIM swap flag (a SIM-swap registration for the subscriber in < 7 days)
4. suspicious recharge (>3 recharges in 24 hours) - Account abuse/micro-recharge churn detectiom

```mermaid
flowchart TD
    Topic[Redpanda: cdr.enriched.filtered] --> Consumer[Fraud Pre-Screener Consumer<br/>group_id=cdr-fraud-screener<br/>batch=500]
    Consumer --> Envelope[Validate EventEnvelope + CDR payload]
    Envelope --> Resolve[Resolve MSISDN<br/>identity_subscribers]
    Resolve --> Config[Load active fraud_rules<br/>conditions JSONB]

    Config --> Velocity[VELOCITY<br/>data: billing_cdr_events<br/>subscriber_id + start_time<br/>rule: count last 1h exceeds max_cdrs_per_hour]
    Config --> Geo[GEOGRAPHIC_ANOMALY<br/>data: current CDR roaming + billing_cdr_events<br/>rule: roaming CDR within window after domestic call]
    Config --> SimSwap[SIM_SWAP<br/>data: identity_registrations<br/>rule: registration_type SIM_SWAP within lookback_days]
    Config --> Recharge[SUSPICIOUS_RECHARGE<br/>data: recharge_orders<br/>rule: completed recharges last 24h exceeds max_recharges_per_24h]

    Velocity --> Merge[Collect matched rule_type strings]
    Geo --> Merge
    SimSwap --> Merge
    Recharge --> Merge

    Merge --> Decision{Any match?}
    Decision -->|No| Noop[No publish<br/>commit offset]
    Decision -->|Yes| Event[Insert fraud_events<br/>cdr_id, subscriber_id, msisdn, rule_triggered, detected_at]
    Event --> Publish[Publish cdr.fraud.flagged<br/>payload fraud_signal=true<br/>rules_matched + trace_id<br/>key=msisdn]
    Publish --> Commit[Commit offset after batch success]
```

# Subscriber Portal

## Balance/Current Plan Lookup
```mermaid
sequenceDiagram
    participant UI as Subscriber Portal
    participant API as FastAPI Balance Router
    participant Valkey as Valkey balance key
    participant DB as PostgreSQL

    UI->>API: request balance + current plan
    API->>Valkey: read live wallet balance
    alt Valkey hit
        Valkey-->>API: balance_paise
    else Valkey miss
        API->>DB: read billing_wallet_balances
        DB-->>API: persisted balance
    end
    API->>DB: read plans_subscriptions + plans_plans
    DB-->>API: active plan + allowances + expiry
    API-->>UI: balance + current plan
```

## Chatbot
```mermaid
flowchart TD
    User[Subscriber] --> Chat[CopilotChat]
    Chat --> Runtime[CopilotKit runtime<br/>/api/chat AG-UI]
    Runtime --> Identity[SupportIdentityMiddleware<br/>JWT + X-Chat-Session-Id]
    Identity --> Support[LangGraph Support Agent<br/>guardrail -> LLM supervisor -> ToolNode]
    Support <--> Checkpoint[LangGraph checkpointer<br/>PostgreSQL if available<br/>InMemory fallback]
    Support --> Trace[LangFuse spans<br/>conditional, best-effort, PII-redacted]

    Support --> Balance{Balance?}
    Balance --> BalanceTool[Tool: balance_lookup]
    BalanceTool --> BAgent[Balance Management Agent<br/>A2A LangGraph]
    BAgent --> ValkeyBal[Valkey<br/>balance:&#123;msisdn&#125;]

    Support --> PlanUsage{Current plan / usage?}
    PlanUsage --> PlanTools[Tools: get_plan / get_usage]
    PlanTools --> PgPlan[PostgreSQL<br/>plans_subscriptions<br/>plans_plans<br/>billing_cdr_events]

    Support --> FAQ{FAQ / policy / plan knowledge?}
    FAQ --> RagTool[Tool: rag_search_tool]
    RagTool --> Retriever[HybridRetriever<br/>dense + BM25 + RRF]
    Retriever --> MilvusFAQ[Milvus Lite<br/>faq_chunks + plan_vectors]
    Retriever --> RagTrace[LangFuse<br/>rag_retrieval span]

    Support --> Rating{Charge explanation?}
    Rating --> ChargeTool[Tool: charge_explain]
    ChargeTool --> RAgent[Rating Agent<br/>LLM-powered separate LangGraph]
    RAgent --> RatingNodes[Rating ReAct tools<br/>CDR lookup + balance check<br/>time-window charge search]
    RatingNodes --> PgCDR[PostgreSQL<br/>billing_cdr_events<br/>plans_subscriptions<br/>plans_plan_config<br/>billing_transactions]
    RatingNodes --> ValkeyRating[Valkey<br/>current balance fallback path]

    Support --> Reco{Plan recommendation?}
    Reco --> RecoTool[Tool: recommend_plan]
    RecoTool --> MilvusPlans[Milvus Lite<br/>plan_vectors]
    RecoTool --> PgUsage[PostgreSQL<br/>usage profile + population stats + current plan]

    Support --> Recharge{Recharge?}
    Recharge --> ListPlans[Tool: list_plans]
    ListPlans --> PgCatalog[PostgreSQL<br/>active plans]
    Recharge --> RechargeFlow[Tool: recharge_flow]
    RechargeFlow --> Deeplink[Return deeplink only<br/>/subscriber/recharge?plan_id]
    Deeplink --> PortalRecharge[Subscriber portal recharge wizard]
    PortalRecharge --> RechargeAPI[Recharge Router]
    RechargeAPI --> Pay[Simulated payment + tokenized method]
    RechargeAPI --> PgRecharge[PostgreSQL<br/>recharge_orders<br/>billing_transactions<br/>recharge_receipts]
    RechargeAPI --> ValkeyTopup[Valkey INCRBY<br/>balance key]

    Support --> Dispute{Dispute?}
    Dispute --> TicketTool[Tool: ticket_create]
    TicketTool --> PgSupport[PostgreSQL<br/>support_tickets]

    Support --> End[Session end / explicit close]
    End --> Conclusion[Conclusion Agent]
    Conclusion --> Notify[Notification Agent]
    Notify --> Topic[Redpanda<br/>notification.events]
```

# Ops Portal

## Data plan forecasting
```mermaid
sequenceDiagram
    participant UI as Ops Dashboard
    participant API as FastAPI Ops Router
    participant ML as scikit-learn Plan Demand Forecast
    participant DB as PostgreSQL

    UI->>API: request 30-90 day plan forecast
    API->>ML: run forecast job
    ML->>DB: read plans, subscriptions, CDR usage summaries
    DB-->>ML: historical demand signals
    ML->>DB: upsert ops_forecast_results
    ML-->>API: forecast series + confidence bands
    API-->>UI: chart data
```

## Subscriber growth forecasting
```mermaid
sequenceDiagram
    participant UI as Ops Dashboard
    participant API as FastAPI Ops Router
    participant ML as scikit-learn Subscriber Growth Forecast
    participant DB as PostgreSQL

    UI->>API: request 3-month growth forecast
    API->>ML: run forecast job
    ML->>DB: read registrations, subscribers, subscriptions, KPI view
    DB-->>ML: activation + churn history
    ML->>DB: upsert ops_forecast_results
    ML-->>API: activation/churn projection
    API-->>UI: chart data
```
