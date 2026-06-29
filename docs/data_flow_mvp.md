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
  ├─► Dedup ──► Redis SET (cdr_id, TTL=24h)
  │
  ├─► Balance Update ──► Redis INCRBY pipeline (atomic)
  │                         └─► Async flush → PostgreSQL (bulk upsert, 2s or 5K)
  │
  └─► Filter & Publish ──► Redpanda: cdr.enriched.filtered
                              ├─► Fraud Pre-Screener (Kafka consumer, same Python codebase)
                              └─► Notification Trigger (Kafka consumer, same Python codebase)
```

## Fraud screener
_To be created_

# Subscriber Portal

## Balance/Current Plan Lookup
_To be created_

## Chatbot
_To be created: Create 1 flow diagram that covers all these. Ensure it covers tools, systems used (Redis/Postgres/Milvus etc)_
1. Balance/current plan requests
2. FAQ requests
3. Rating agent
4. Plan recommendation request
5. Recharge

# Ops Portal

## Data plan forecasting

## Subscriber growth forecasting