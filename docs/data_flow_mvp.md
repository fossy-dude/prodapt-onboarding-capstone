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
```mermaid
sequenceDiagram
    participant CDR as cdr.enriched.filtered
    participant Rules as Fraud Pre-Screener
    participant Flagged as cdr.fraud.flagged
    participant Agent as LangGraph Fraud Agent
    participant DB as PostgreSQL
    participant Alerts as fraud.alerts
    participant UI as Fraud Dashboard WS

    CDR->>Rules: CDR + trace_id
    alt Rule pass
        Rules-->>CDR: no fraud action
    else Rule flag
        Rules->>Flagged: flagged CDR + triggered rules
        Flagged->>Agent: async escalation
        Agent->>DB: read 7-day subscriber history
        Agent->>DB: write fraud_cases verdict
        alt confirmed risk
            Agent->>DB: write fraud_blacklist
            Agent->>Alerts: supervisor alert
            Alerts->>UI: live anomaly/case update
        end
    end
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
    Chat --> Stream[POST /api/chat/stream<br/>CopilotKit AG-UI]
    Stream --> Support[LangGraph Support Agent]
    Support <--> Ctx[Valkey<br/>chat_context session, 2h TTL]
    Support --> Trace[LangFuse traces]

    Support --> Balance{Balance / plan?}
    Balance --> BAgent[Balance Management Agent]
    BAgent --> ValkeyBal[Valkey<br/>balance key]
    BAgent --> PgPlan[PostgreSQL<br/>billing_wallet_balances<br/>plans_subscriptions<br/>plans_plans]

    Support --> FAQ{FAQ?}
    FAQ --> MilvusFAQ[Milvus hybrid search<br/>faq_chunks]

    Support --> Rating{Charge explanation?}
    Rating --> RAgent[Rating Agent]
    RAgent --> PgCDR[PostgreSQL<br/>billing_audit_log<br/>plans_plans]

    Support --> Reco{Plan recommendation?}
    Reco --> RecoTool[Plan Recommendation Tool]
    RecoTool --> MilvusPlans[Milvus hybrid search<br/>plan_vectors]
    RecoTool --> PgUsage[PostgreSQL<br/>usage summaries + plans]
    RecoTool --> Feedback[PostgreSQL<br/>recommendation_feedback]

    Support --> Recharge{Recharge?}
    Recharge --> RechargeAPI[Recharge Router]
    RechargeAPI --> Pay[Simulated payment + tokenized method]
    RechargeAPI --> PgRecharge[PostgreSQL<br/>recharge_orders<br/>billing_transactions<br/>recharge_receipts]
    RechargeAPI --> ValkeyTopup[Valkey INCRBY<br/>balance key]

    Support --> End[Conclusion Agent]
    End --> Notify[Notification Agent]
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
