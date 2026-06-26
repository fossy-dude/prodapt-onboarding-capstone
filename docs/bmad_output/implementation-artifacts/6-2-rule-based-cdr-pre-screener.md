---
baseline_commit: 89d48fe
---

# Story 6.2: Rule-Based CDR Pre-Screener

Status: ready-for-dev

## Story

As a **platform engineer**,
I want every CDR event on `cdr.enriched.filtered` to be evaluated against a set of anomaly rules before reaching the Fraud Detection Agent,
so that only genuinely suspicious events are escalated to the expensive LLM-powered agent.

## Acceptance Criteria

1. **Given** a CDR event is published to `cdr.enriched.filtered`, **When** the rule-based pre-screener processes it, **Then** it evaluates the event against 4 rule types: velocity (>50 CDRs in 1 hour for a single MSISDN), geographic anomaly (roaming event within 30 minutes of a domestic call), SIM swap flag (a SIM-swap registration for the subscriber), suspicious recharge (>3 recharges in 24 hours) (FR-60). [Source: epics.md:1812]
2. **And** events matching any rule have `fraud_signal = true` appended to the event and are published to `cdr.fraud.flagged` (ARCH-10). [Source: epics.md:1814]
3. **And** events with no match are forwarded to the `cdr.enriched.filtered` consumer without escalation. [Source: epics.md:1816]
4. **And** rule thresholds (velocity limit, recharge count) are read from DB config records (not hardcoded) (NFR-20 precedent). [Source: epics.md:1818]
5. **And** a Flyway migration creates: `fraud_rules` table (rule_id, rule_type, threshold_value, is_active), `fraud_events` table (event_id UUIDv7, cdr_id, msisdn, rule_triggered, detected_at). [Source: epics.md:1820]

## Tasks / Subtasks

- [ ] **Task 1: Flyway migration V11 — fraud_events + fraud_rules seed** (AC: #4, #5)
  - [ ] Create `service_webapp/db/migrations/V11__fraud_pre_screener.sql`.
  - [ ] Version note: V10 is reserved for `mv_usage_population_stats` (Story 5.9, currently untracked). Use V11 for fraud. If V10 is not yet committed at implementation time, renumber to the next free version — never collide with V10.
  - [ ] **fraud_rules**: the table already exists in V1 (`id UUIDv4, rule_name, rule_type, conditions JSONB, severity, is_active`). The AC's `threshold_value` maps onto the EXISTING `conditions JSONB` column (audit confirms `conditions` is unused outside DDL) — do NOT add a redundant `threshold_value` column. Mapping: AC `rule_id` → existing `id`; `rule_type` → existing `rule_type`; `threshold_value` → existing `conditions`; `is_active` → existing `is_active`. [Source: audit 2026-06-25; V1__baseline_schema.sql:411-421]
  - [ ] Seed the 4 rule config rows (idempotent — fraud_rules is a reference/config table, UUIDv4, manually managed):
    ```sql
    INSERT INTO fraud_rules (id, rule_name, rule_type, conditions, severity, is_active) VALUES
      (gen_random_uuid(), 'Velocity burst',       'VELOCITY',
       '{"max_cdrs_per_hour": 50}'::jsonb, 'high', TRUE),
      (gen_random_uuid(), 'Geographic anomaly',   'GEOGRAPHIC_ANOMALY',
       '{"window_minutes": 30}'::jsonb, 'medium', TRUE),
      (gen_random_uuid(), 'SIM swap flag',        'SIM_SWAP',
       '{"lookback_days": 7}'::jsonb, 'high', TRUE),
      (gen_random_uuid(), 'Suspicious recharge',  'SUSPICIOUS_RECHARGE',
       '{"max_recharges_per_24h": 3}'::jsonb, 'medium', TRUE)
    ON CONFLICT (rule_name) DO UPDATE SET conditions = EXCLUDED.conditions, is_active = TRUE;
    ```
  - [ ] **fraud_events** (does NOT exist — create):
    ```sql
    CREATE TABLE fraud_events (
        event_id       UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
        cdr_id         UUID NOT NULL,
        subscriber_id  UUID NOT NULL REFERENCES identity_subscribers (id),
        msisdn         VARCHAR(15) NOT NULL,
        rule_triggered VARCHAR(50) NOT NULL,
        detected_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        resolved       VARCHAR(20),   -- NULL = open; 'false_positive' set by Story 6.3 agent
        agent_trace_id UUID,          -- set by Story 6.3 agent
        created_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        CONSTRAINT fk_fraud_events_cdr FOREIGN KEY (cdr_id) REFERENCES billing_cdr_events (id)
    );
    CREATE INDEX idx_fraud_events_subscriber_id ON fraud_events (subscriber_id);
    CREATE INDEX idx_fraud_events_detected_at   ON fraud_events (detected_at);
    CREATE INDEX idx_fraud_events_rule          ON fraud_events (rule_triggered);
    ```
    `resolved` and `agent_trace_id` are added now (forward-compat for 6.3) so the agent does not need its own migration to touch this table.

- [ ] **Task 2: Extend synthetic seeder for fraud signals the rules need** (AC: #1, supports eval 6.1)
  - [ ] In `scripts/generate_synthetic_data.py` extend `_build_fraud_plan` / add generators so the pre-screener's 4 rules have data to fire on. Today the seeder models `sim_swap` as IMEI rotation only and writes NO `identity_registrations` rows; it has no `suspicious_recharge` signal at all. [Source: audit 2026-06-25]
  - [ ] **SIM_SWAP registration rows**: for each subscriber assigned the `sim_swap` signal, INSERT an `identity_registrations` row (`registration_type='SIM_SWAP'`, `subscriber_id`, `sim_serial=<imei_after>`, `status='REGISTRATION_COMPLETE'`, `registration_id='REG-{YYYYMMDD}-{8hex}'`, `submitted_at=<swap_point>`). Required columns from V1+V3: `registration_id` is NOT NULL UNIQUE. This is the source the SIM_SWAP rule queries (user decision: derive SIM-swap from registrations). [Source: V3__registration_extensions.sql:33-47; user decision 2026-06-25]
  - [ ] **suspicious_recharge signal**: add it to `FRAUD_SIGNAL_NAMES`. For subscribers assigned it, generate >3 `recharge_orders` rows within a 24h window (`status='COMPLETED'`, distinct `idempotency_key`, `created_at` clustered in the window). Verify the seeder already emits `recharge_orders` rows — if not, add a minimal recharge generator (recharge_orders cols: `subscriber_id, plan_id, amount_paise, idempotency_key, status, created_at`).
  - [ ] Keep existing signals (`velocity_burst`, `roaming_abuse`, `unique_destinations`, `multi_tower`) — they still set `billing_cdr_events.fraud_flag` and feed the 6.3 LLM agent's richer analysis even though only velocity/geo are pre-screener rules.
  - [ ] Update `write_fraud_report()` (`temp/fraud_report.json`) so the per-subscriber `fraud_types` reflects the new signal set.

- [ ] **Task 3: Screener package in cdr-pipeline** (AC: #1, #2, #3)
  - [ ] Create `cdr-pipeline/src/screener/__init__.py`, `rules.py`, `publisher.py`.
  - [ ] `rules.py` — pure functions, each takes a DB connection + the CDR event + rule config and returns a bool:
    - `is_velocity_burst(conn, subscriber_id, ts, threshold) -> bool` — `SELECT COUNT(*) FROM billing_cdr_events WHERE subscriber_id=%s AND start_time BETWEEN %s - interval '1 hour' AND %s` ; match if `count > threshold["max_cdrs_per_hour"]`. Indexed by subscriber_id+start_time.
    - `is_geographic_anomaly(conn, subscriber_id, ts, threshold) -> bool` — current event is roaming; check `EXISTS (SELECT 1 FROM billing_cdr_events WHERE subscriber_id=%s AND roaming=FALSE AND start_time BETWEEN %s - interval '%s minutes' AND %s)` with `window_minutes` from threshold.
    - `is_sim_swap(conn, subscriber_id, threshold) -> bool` — `SELECT EXISTS(SELECT 1 FROM identity_registrations WHERE subscriber_id=%s AND registration_type='SIM_SWAP' AND submitted_at >= NOW() - interval '%s days')` using `lookback_days`.
    - `is_suspicious_recharge(conn, subscriber_id, ts, threshold) -> bool` — `SELECT COUNT(*) FROM recharge_orders WHERE subscriber_id=%s AND status='COMPLETED' AND created_at >= %s - interval '24 hours'` ; match if `count > threshold["max_recharges_per_24h"]`.
    - A dispatcher `evaluate_rules(conn, cdr_event, rule_configs) -> list[str]` returns the list of matched rule_type strings (empty = no match). Short-circuit: a CDR can match multiple rules; record the first/primary but evaluate all 4 cheaply (indexed lookups).
  - [ ] MSISDN resolution: the CDR event carries `subscriber_id`, not `msisdn`. Resolve once via `SELECT msisdn FROM identity_subscribers WHERE id=%s` and reuse for all rules + the published envelope. (cdr-pipeline has its own postgres adapter; mirror the balance consumer's DB access.)
  - [ ] `publisher.py` — `publish_flagged(producer, cdr_event, msisdn, rules_matched, trace_id)`: builds an `EventEnvelope` (`event_type="fraud.flagged"`, payload = CDR payload + `fraud_signal=True` + `rules_matched=[...]`), publishes to `cdr.fraud.flagged` with `key=msisdn` (ARCH-10 — fraud topics keyed by msisdn) via the existing `KafkaProducer.publish(topic, key, envelope)`.

- [ ] **Task 4: Screener consumer (cdr.enriched.filtered → cdr.fraud.flagged)** (AC: #1, #2, #3)
  - [ ] Add a consumer in `cdr-pipeline/src/screener/` mirroring `cdr-pipeline/src/consumer/batch_processor.py`: `AIOKafkaConsumer("cdr.enriched.filtered", group_id="cdr-fraud-screener", enable_auto_commit=False, auto_offset_reset="earliest")`. The group id is already defined as `KafkaConsumerGroups.fraud_screener` in `cdr-pipeline/src/core/config.py`. [Source: cdr-pipeline config; architecture.md#1.7.6]
  - [ ] Batch loop: `getmany(max_records=500, timeout_ms=1000)` → per record `EventEnvelope.model_validate_json` (fail → DLQ via `dlq/handler.py`) → `TypeAdapter(CdrEvent).validate_python(payload)` → resolve msisdn → `evaluate_rules(...)`.
  - [ ] Match: INSERT a `fraud_events` row (`cdr_id`, `subscriber_id`, `msisdn`, `rule_triggered`), set the event's `fraud_signal=True`, `publish_flagged(...)` to `cdr.fraud.flagged`.
  - [ ] No match: do nothing further (AC #3 "forwarded without escalation" = not published to `cdr.fraud.flagged`; there is no second topic to forward to — `cdr.enriched.filtered` is already the post-deduction stream other consumers read). Commit offset once per batch (at-least-once; `fraud_events` INSERT + `cdr.fraud.flagged` publish must be idempotent on replay — see dev notes).
  - [ ] Wire the screener as a second asyncio task in `cdr-pipeline/src/main.py` lifespan alongside the balance consumer (same broker, separate group). Keep it OFF the balance hot path (ARCH-14): the screener consumes `cdr.enriched.filtered` independently after deduction.
  - [ ] The screener is deterministic/non-LLM (the "synchronous" in FR-60 means rule-based, not inline in the balance consumer). The LLM agent (6.3) is the async part. [Source: architecture.md#1.4.3, ARCH-14]

- [ ] **Task 5: Load rule thresholds from DB (NFR-20)** (AC: #4)
  - [ ] At screener startup, load active rules: `SELECT id, rule_type, conditions, is_active FROM fraud_rules WHERE is_active=TRUE`. Cache in-memory; refresh on a TTL (e.g. 60s) or keep simple — reload per batch is too chatty; reload every N batches. Thresholds live in `conditions` JSONB (the AC `threshold_value`).
  - [ ] Pass each rule's `conditions` dict to the matching rule function. No hardcoded `50` / `30` / `3` in `rules.py` — all from DB.

- [ ] **Task 6: Tests** (AC: #1–#5)
  - [ ] `cdr-pipeline/tests/unit/test_screener_rules.py` (mocked conn): velocity `count==50` → no match, `51` → match; geo — roaming event with domestic call 29min ago → match, 31min ago → no match, non-roaming current event → skip; sim_swap — registration within 7d → match, none → no match; recharge — 3 completed in 24h → no match, 4 → match, 2 in 24h + others older → no match.
  - [ ] `cdr-pipeline/tests/unit/test_screener_dispatcher.py`: `evaluate_rules` returns all matched rule_types; empty when none; thresholds parsed from the `conditions` JSONB shape.
  - [ ] `cdr-pipeline/tests/integration/test_screener_consumer.py` (`@pytest.mark.slow`, testcontainers kafka + postgres): publish a `cdr.enriched.filtered` envelope for a fraud subscriber seeded with a SIM_SWAP registration; assert a `fraud_events` row is inserted AND a `cdr.fraud.flagged` message is produced with `fraud_signal=True`. Publish a clean CDR → no `fraud_events` row, no `cdr.fraud.flagged` message.
  - [ ] `service_webapp/tests/integration/test_fraud_migration.py`: assert V11 applies cleanly on V1 baseline, `fraud_rules` has exactly 4 active rows, `fraud_events` accepts inserts with the documented columns.

## Dev Notes

### Pre-screener placement — cdr-pipeline, NOT service_webapp

architecture.md §1.4.1/§1.12.1 places the Fraud Pre-Screener in `cdr-pipeline/` as a Kafka consumer sharing the same Postgres+Valkey. The MVP data-flow shows it consuming `cdr.enriched.filtered`. service_webapp does NOT run CDR consumers (NFR-18: no HTTP between the two; cdr-pipeline owns the CDR→balance→fraud-signal path). The screener is net-new: `cdr-pipeline/src/screener/` does not exist; `cdr.enriched.filtered` currently has a producer (balance consumer) but NO consumer. [Source: architecture.md#1.4.1, #1.4.3, #1.12.1; ARCH-14; NFR-18]

### "Synchronous in pipeline" vs async consumer (FR-60 vs ARCH-14)

FR-60 says pre-screening "executes synchronously in the CDR processing pipeline"; ARCH-14 says the AGENT runs async after deduction on `cdr.enriched.filtered`. These are consistent: the PRE-SCREENER is a deterministic, rule-based Kafka consumer (fast, no LLM) on `cdr.enriched.filtered`; the AGENT (6.3) is the slow async LLM consumer on `cdr.fraud.flagged`. "Synchronous" = deterministic/non-LLM, NOT inline in the balance consumer. The balance hot path (NFR-1 ≤200ms) is untouched. [Source: architecture.md#1.4.3]

### AC #3 — "forwarded without escalation" means no-op, not a second publish

The pre-screener CONSUMES `cdr.enriched.filtered`. A non-matching event simply is not published to `cdr.fraud.flagged`. There is no additional topic to forward to — `cdr.enriched.filtered` is already the post-deduction stream. Do NOT invent a re-publish. [Source: epics.md:1816; architecture.md#1.7.6 topic table]

### fraud_rules.threshold_value → reuse conditions JSONB (no new column)

The V1 `fraud_rules` table already has a `conditions JSONB` column purpose-built for rule params; it is UNUSED outside DDL (audit 2026-06-25). Adding a separate `threshold_value` column would be redundant. The AC's `threshold_value` maps onto `conditions`. This honors "extend via migration but check existing-column usage first; reuse where semantically equal" (user decision 2026-06-25). `fraud_rules` needs NO schema change — only seed INSERTs. [Source: V1__baseline_schema.sql:411-421; audit 2026-06-25]

### fraud_events is the only new table; columns added for 6.3 forward-compat

`fraud_events` does not exist. Create it with the AC columns plus `subscriber_id` (the agent needs it for 7-day history lookup), `resolved` (6.3 marks `false_positive`), and `agent_trace_id` (6.3 link) added NOW so 6.3 does not need to alter this table. Audit confirms no code reads/writes fraud tables today — additions are zero-risk. [Source: audit 2026-06-25]

### SIM-swap signal — derive from identity_registrations (user decision)

There is no `sim_swap_flag` column anywhere. The SIM_SWAP rule queries `identity_registrations WHERE registration_type='SIM_SWAP'`. `registration_type` is `VARCHAR(30) NOT NULL` with NO CHECK/enum (V1:60) — adding the value `'SIM_SWAP'` requires no schema change. Today the seeder writes no registration rows and no `'SIM_SWAP'` value exists, so Task 2 MUST extend the seeder to plant SIM_SWAP registrations for the `sim_swap` fraud subscribers. `registration_id` (NOT NULL UNIQUE, `REG-{YYYYMMDD}-{8hex}`) is required on every row (V3). [Source: V1__baseline_schema.sql:57-71; V3__registration_extensions.sql:33-47; user decision 2026-06-25]

### At-least-once + idempotency on replay

cdr-pipeline commits offset once per batch; a crash mid-batch replays records. The `fraud_events` INSERT + `cdr.fraud.flagged` publish must tolerate replay: guard the INSERT with `ON CONFLICT DO NOTHING` keyed on `cdr_id` (add `CONSTRAINT uq_fraud_events_cdr UNIQUE (cdr_id)` in the migration — one fraud_events row per CDR), and accept that `cdr.fraud.flagged` may be published twice (the agent consumer in 6.3 dedups on `cdr_id`). [Source: 2-2-cdr-ingestion-consumer-dedup-dlq.md dedup pattern; architecture.md#1.4.3]

### Kafka envelope + key conventions

Reuse `cdr-pipeline/src/models/envelope.py` `EventEnvelope.new(event_type, payload, trace_id, ...)`. Publish to `cdr.fraud.flagged` with `key=msisdn` (ARCH-10 — fraud topics keyed by msisdn, unlike `cdr.raw`/`cdr.enriched.filtered` keyed by subscriber_id). Preserve the original `trace_id` (W3C) from the source envelope through the flagged envelope (NFR-17 — traceparent header + trace_id body on every message). [Source: architecture.md#1.7.6, #1.11.4; ARCH-10, ARCH-11; NFR-17]

### CDR column names — verified from seeder COPY

`billing_cdr_events` columns (from the seeder COPY): `session_id, subscriber_id, cdr_type, telecom_circle, cell_tower_id, roaming, cost_paise, status, fraud_flag, start_time, end_time, from_number, to_number, call_direction, duration_seconds, call_status, network_type, downloaded_mb, uploaded_mb, volume_mb, apn, imei, operator_id`. Use `cost_paise` (NOT `charge_paise` — Story 5.9 had this wrong), `roaming BOOL`, `start_time` for windows. The CDR `id` PK = the app-supplied `cdr_id` (UUIDv7). [Source: scripts/generate_synthetic_data.py:300-308; audit 2026-06-25]

### Topics already provisioned

`cdr-pipeline/scripts/provision_topics.py` already provisions `cdr.enriched.filtered` (24p), `cdr.fraud.flagged` (6p), `fraud.alerts` (6p). No topic-provisioning work in this story. [Source: architecture digest; provision_topics.py]

### Project Structure Notes

- New migration: `service_webapp/db/migrations/V11__fraud_pre_screener.sql` (fraud_events table + fraud_rules seed; fraud_rules schema unchanged)
- Modified: `scripts/generate_synthetic_data.py` (SIM_SWAP registrations, suspicious_recharge signal, recharge_orders if absent, fraud_report update)
- New package: `cdr-pipeline/src/screener/{__init__.py,rules.py,publisher.py,consumer.py}`
- Modified: `cdr-pipeline/src/main.py` (wire screener consumer as lifespan task)
- New tests: `cdr-pipeline/tests/unit/test_screener_rules.py`, `test_screener_dispatcher.py`; `cdr-pipeline/tests/integration/test_screener_consumer.py`; `service_webapp/tests/integration/test_fraud_migration.py`
- No service_webapp routers, no agent code, no frontend. (DB migrations live in service_webapp even though the screener runs in cdr-pipeline — Flyway owns all schema.)

### References

- [Source: epics.md:1798-1820 — Story 6.2 acceptance criteria]
- [Source: epics.md#1.2.3 ARCH-10 — Kafka topics; ARCH-14 — agent async off hot path; ARCH-11 — envelope]
- [Source: architecture.md#1.4.1, #1.4.3, #1.7.6, #1.11.4 — pre-screener placement, data flow, topics, envelope]
- [Source: V1__baseline_schema.sql:411-455 — fraud_rules, fraud_cases, fraud_blacklist DDL; 57-71 identity_registrations; 178-189 billing_cdr_events.fraud_flag]
- [Source: V3__registration_extensions.sql:33-47 — registration_id NOT NULL UNIQUE, status width]
- [Source: audit 2026-06-25 — fraud tables unused outside DDL; conditions JSONB reusable; no sim_swap_flag; seeder writes no registrations/recharges]
- [Source: scripts/generate_synthetic_data.py:300-355 — CDR COPY columns, _build_fraud_plan, sim_swap IMEI model]
- [Source: 2-2-cdr-ingestion-consumer-dedup-dlq.md — consumer/dedup/DLQ pattern; 2-3 batch processor pattern]
- [Source: user decision 2026-06-25 — extend via migrations; SIM-swap derived from registrations]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
