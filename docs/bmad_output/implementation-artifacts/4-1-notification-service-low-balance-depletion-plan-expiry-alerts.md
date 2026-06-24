---
baseline_commit: b1dda60
---

# Story 4.1: Notification Service — Low Balance, Depletion & Plan Expiry Alerts

Status: in-progress

## Story

As a **subscriber**,
I want to receive simulated SMS and push notifications when my balance drops low, depletes, or my plan is about to expire,
so that I can recharge proactively before service is interrupted.

## Acceptance Criteria

1. **Given** a CDR deduction reduces a subscriber's balance below ₹10 (1000 paise), **When** the balance engine flushes to Postgres, **Then** a notification event is published to `notification.events` with type=LOW_BALANCE, subscriber_id, balance_paise, trace_id (FR-18). [Source: epics.md:1338–1344]
2. **And** the threshold value (1000 paise default) is read from `notification_threshold_config` DB record (key='low_balance_threshold_paise') — not hardcoded (NFR-20). [Source: epics.md:1344]
3. **Given** a subscriber's balance reaches 0 or goes negative, **When** the balance engine processes the deduction, **Then** a BALANCE_DEPLETED notification event is published to `notification.events` (FR-19). [Source: epics.md:1346–1350]
4. **Given** a scheduled job runs once daily at 08:00 IST (02:30 UTC), **When** it finds subscribers whose active plan expires within 3 days, **Then** a PLAN_EXPIRY_REMINDER notification event is published for each affected subscriber (FR-20). [Source: epics.md:1352–1358]
5. **And** the lead-time (3 days default) is read from `notification_threshold_config` DB record (key='plan_expiry_reminder_days') — not hardcoded (NFR-20). [Source: epics.md:1358]
6. **Given** a data-type CDR deduction reduces a subscriber's data allowance below 10% remaining, **When** the service_webapp DATA_NUDGE consumer processes the CDR, **Then** a DATA_NUDGE notification event is published to `notification.events` (FR-21). [Source: epics.md:1360–1364]
7. **And** all notification events follow the Kafka EventEnvelope schema (ARCH-11), keyed by msisdn on the `notification.events` topic. [Source: epics.md:1366; architecture.md:598–601]
8. **And** a Flyway migration `V6__notification_threshold_config.sql` creates the `notification_threshold_config` table and seeds the two default config rows. [Source: architecture.md:432–460]

## Tasks / Subtasks

- [x] **Task 1: Flyway migration — notification_threshold_config** (AC: #2, #5, #8)
  - [x] Create `service_webapp/db/migrations/V7__notification_threshold_config.sql`. Table DDL: `notification_threshold_config(id UUID DEFAULT gen_random_uuid() PRIMARY KEY, key VARCHAR(100) UNIQUE NOT NULL, value TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL, modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL)`. Apply the `set_modified_at()` trigger (already defined in V2). [Source: architecture.md:380–384; V2__modified_at_trigger.sql]
  - [x] Seed two rows: `(key='low_balance_threshold_paise', value='1000')` and `(key='plan_expiry_reminder_days', value='3')`. Use `INSERT ... ON CONFLICT DO NOTHING` so re-runs are idempotent. [Source: architecture.md:434–444]

- [ ] **Task 2: cdr-pipeline notification trigger module** (AC: #1, #3)
  - [ ] Create `cdr-pipeline/src/consumer/notification_trigger.py`. Define `NotificationTrigger` dataclass holding the `KafkaProducer` and the in-memory `low_balance_threshold_paise: int`. Expose `async def check_and_publish(self, msisdn: str, subscriber_id: str, balance_after: int, trace_id: str) -> None` — publishes LOW_BALANCE when `0 < balance_after < threshold`, BALANCE_DEPLETED when `balance_after <= 0`. Each publishes `EventEnvelope.new(event_type="notification.balance", payload={...}, trace_id=trace_id)` via `KafkaProducer.publish("notification.events", key=msisdn, envelope=...)`. [Source: cdr-pipeline/src/adapters/kafka.py; cdr-pipeline/src/models/envelope.py]
  - [ ] Payload shapes: LOW_BALANCE → `{type: "LOW_BALANCE", subscriber_id, msisdn_last4: msisdn[-4:], balance_paise, threshold_paise}`; BALANCE_DEPLETED → `{type: "BALANCE_DEPLETED", subscriber_id, msisdn_last4: msisdn[-4:]}`. [Source: architecture.md:598–601]
  - [ ] `NotificationTrigger` is constructed once at startup with threshold loaded from `notification_threshold_config` via Postgres. Threshold is cached in-memory — NOT re-queried per CDR. [Source: architecture.md NFR-20]
  - [ ] Both LOW_BALANCE and BALANCE_DEPLETED publish only on the **first** crossing per session: add a `_notified: set[str]` (keyed by `"{msisdn}:{type}"`) to avoid repeated events on consecutive CDRs below threshold. Clear entries when balance rises above threshold (recharge path calls `clear_notified`). [Source: epics.md:1338–1366; idempotency principle]

- [ ] **Task 3: Wire NotificationTrigger into BalanceEngine** (AC: #1, #3)
  - [ ] Modify `cdr-pipeline/src/consumer/balance_writer.py`. Add optional `notification_trigger: NotificationTrigger | None = None` parameter to `BalanceEngine.__init__`. Store as `self._notification_trigger`. [Source: cdr-pipeline/src/consumer/balance_writer.py:BalanceEngine.__init__]
  - [ ] In `BalanceEngine.deduct()`, after the `INCRBY` line (after `balance_after` is computed), add: `if self._notification_trigger is not None: asyncio.create_task(self._notification_trigger.check_and_publish(msisdn, sub_id_str, balance_after, span_trace_id))`. The `asyncio.create_task` keeps the hot path O(1) — no `await`. [Source: balance_writer.py:BalanceEngine.deduct(); architecture.md:NFR P95 ≤ 200ms]
  - [ ] `trace_id` for the notification envelope: extract from the current OTEL span using `span.get_span_context().trace_id` formatted as 32 hex chars, or fall back to `cdr.cdr_id` hex. Pass as `str`.
  - [ ] Wire `NotificationTrigger` construction into `cdr-pipeline/src/main.py` lifespan: after `kafka_producer.start()`, query `notification_threshold_config` for `low_balance_threshold_paise`, construct `NotificationTrigger`, pass to `BalanceEngine`. [Source: cdr-pipeline/src/main.py lifespan]

- [ ] **Task 4: DATA_NUDGE consumer in service_webapp** (AC: #6, #7)
  - [ ] Create `service_webapp/src/services/data_nudge_consumer.py`. Async function `run_data_nudge_consumer(db, producer)` that subscribes to `cdr.enriched.filtered` with group_id=`"cdr-notifications"` (from `KafkaConsumerGroups.notifications` equivalent in service_webapp settings). Filters to `cdr_type == "data"` payloads only. [Source: architecture.md:598; cdr-pipeline/src/core/config.py:KafkaConsumerGroups]
  - [ ] For each DataCdr event: resolve `subscriber_id` from envelope payload → look up active `plans_subscriptions` + `plans_plans.data_limit_mb` → SUM `volume_mb` from `billing_cdr_events` for the active plan window (raw SQL via `db/billing/queries.py`). If `data_limit_mb > 0` and `pct_remaining = (data_limit_mb - sum_mb) / data_limit_mb < 0.10` → publish DATA_NUDGE envelope. [Source: epics.md:1360–1364; architecture.md:461]
  - [ ] DATA_NUDGE payload: `{type: "DATA_NUDGE", subscriber_id, msisdn_last4, data_mb_used, data_limit_mb, pct_remaining}`. Key=msisdn on `notification.events`. [Source: epics.md:1360–1364]
  - [ ] Add `get_active_plan_data_quota(db, subscriber_id) -> tuple[float, float] | None` (data_mb_used, data_limit_mb) to `service_webapp/src/db/billing/queries.py`. Raw SQL join: `plans_subscriptions` WHERE status='active' JOIN `plans_plans` → get data_limit_mb and plan window dates; then SUM `billing_cdr_events.volume_mb` WHERE subscriber_id AND start_time BETWEEN window. [Source: architecture.md:461; V1__baseline_schema.sql]
  - [ ] Wire `run_data_nudge_consumer` into `service_webapp/src/main.py` lifespan alongside the existing `notification_consumer_task`. [Source: service_webapp/src/main.py:lifespan]

- [ ] **Task 5: PLAN_EXPIRY_REMINDER scheduler** (AC: #4, #5)
  - [ ] Add `apscheduler>=3.10` to `service_webapp/pyproject.toml` `[project.dependencies]`. Also add to all tox env `deps` lists that include `aiokafka` (unit, integration). [Source: service_webapp/pyproject.toml]
  - [ ] Create `service_webapp/src/services/notification_scheduler.py`. Async function `run_plan_expiry_check(db, producer, lead_days: int) -> None`. SQL: SELECT `identity_subscribers.id, identity_subscribers.msisdn, plans_subscriptions.end_date` FROM `plans_subscriptions` JOIN `identity_subscribers` ON subscriber_id=identity_subscribers.id WHERE status='active' AND end_date BETWEEN NOW() AND NOW() + lead_days * INTERVAL '1 day'. For each row publish PLAN_EXPIRY_REMINDER envelope. [Source: epics.md:1352–1358; V1__baseline_schema.sql plans_subscriptions]
  - [ ] PLAN_EXPIRY_REMINDER payload: `{type: "PLAN_EXPIRY_REMINDER", subscriber_id, msisdn_last4: msisdn[-4:], expiry_date: end_date.isoformat(), days_remaining: (end_date - today).days}`. Key=msisdn on `notification.events`. [Source: epics.md:1352–1358]
  - [ ] In `service_webapp/src/main.py` lifespan: after DB pool starts, query `notification_threshold_config` for `plan_expiry_reminder_days` (default 3), construct `AsyncIOScheduler`, add `CronTrigger(hour=2, minute=30)` job (02:30 UTC = 08:00 IST), start scheduler, stop in shutdown. [Source: apscheduler docs; architecture.md IST=UTC+5:30]

- [ ] **Task 6: Tests** (AC: #1–#8)
  - [ ] `cdr-pipeline/tests/unit/test_notification_trigger.py`: mock `KafkaProducer`. LOW_BALANCE fires when `balance_after=500, threshold=1000`; BALANCE_DEPLETED fires when `balance_after=0`; nothing fires when `balance_after=2000`. Dedup: second LOW_BALANCE below threshold for same msisdn is suppressed. [Source: architecture.md:NFR-20; idempotency]
  - [ ] `service_webapp/tests/unit/test_notification_scheduler.py`: mock DB returning 2 subscribers with plan expiring in 2 days → verify `producer.send` called twice with PLAN_EXPIRY_REMINDER; zero subscribers → no calls.
  - [ ] `service_webapp/tests/unit/test_data_nudge_consumer.py`: mock DB returning data_mb_used=9.5, data_limit_mb=10 (5% remaining) → DATA_NUDGE published; data_mb_used=8, data_limit_mb=10 (20% remaining) → no publish; unlimited plan (data_limit_mb=0) → no publish.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres + Valkey (testcontainers). Seed V6 migration rows. Verify threshold read from DB. [Source: service_webapp/tests/conftest.py testcontainers pattern]

## Dev Notes

### Scope boundary

- **DOES:** `notification_threshold_config` migration, `NotificationTrigger` in cdr-pipeline, LOW_BALANCE/BALANCE_DEPLETED triggers from `BalanceEngine.deduct()`, DATA_NUDGE consumer in service_webapp, PLAN_EXPIRY_REMINDER APScheduler job, `apscheduler` dep.
- **DOES NOT:** notification preferences check (4.2), notification logging to `notifications_events` table (4.2), WebSocket portal broadcast (already in Story 2.9 `main.py` broadcaster), rate limiting (4.3), USSD (4.4).

### Hot path constraint — asyncio.create_task, never await

`BalanceEngine.deduct()` is on the P95 ≤ 200ms path. The notification trigger MUST use `asyncio.create_task(trigger.check_and_publish(...))` — never `await`. Task exceptions are swallowed by the event loop unless a handler is set; add `task.add_done_callback(lambda t: t.exception() and logger.error(...))` to surface failures without blocking.

### Threshold cache — load at startup, never per-CDR

`NotificationTrigger` in cdr-pipeline caches `low_balance_threshold_paise` loaded once from `notification_threshold_config` at startup. A restart is required to pick up threshold changes. This is acceptable for MVP (NFR-20 says "not hardcoded" — DB-configurable, not live-reload).

### notification_threshold_config vs notifications_config

The existing `notifications_config` table (`V1__baseline_schema.sql:328`) stores per-notification-type SMS templates and threshold values keyed by `notification_type`. The new `notification_threshold_config` table is a generic key-value store for operational parameters (`low_balance_threshold_paise`, `plan_expiry_reminder_days`) that don't map cleanly to a single notification type. Both tables coexist.

### DATA_NUDGE — service_webapp consumer, not cdr-pipeline

DATA_NUDGE requires querying `plans_plans.data_limit_mb` and aggregating `billing_cdr_events.volume_mb`. cdr-pipeline does NOT have access to plan data (it only tracks wallet paise via Valkey). The DATA_NUDGE consumer lives in service_webapp, consuming `cdr.enriched.filtered` (group_id `cdr-notifications`) and performing the DB join inline. This adds latency relative to the hot path but is acceptable — DATA_NUDGE is a low-priority advisory notification.

### PLAN_EXPIRY_REMINDER — APScheduler AsyncIOScheduler

APScheduler 3.x `AsyncIOScheduler` runs jobs in the same event loop as FastAPI. The cron job is added with `CronTrigger(hour=2, minute=30, timezone="UTC")`. The scheduler is started after the DB pool is available (it needs `db` and `producer` injected). Stop the scheduler in the lifespan shutdown block before closing the DB pool.

### EventEnvelope trace_id in cdr-pipeline

The notification envelope published from `NotificationTrigger.check_and_publish` must carry the same `trace_id` as the CDR that triggered it. Extract from the active OTEL span: `format(trace.get_current_span().get_span_context().trace_id, '032x')`. Pass this string through from `BalanceEngine.deduct()` — the span is still active at that point.

### Idempotency — once-per-crossing dedup

LOW_BALANCE and BALANCE_DEPLETED are published once per threshold crossing, not once per CDR below threshold. The `_notified` set in `NotificationTrigger` tracks `"{msisdn}:LOW_BALANCE"` and `"{msisdn}:BALANCE_DEPLETED"`. The recharge flow (Story 3.5) must call `trigger.clear_notified(msisdn)` on successful recharge so the next low-balance event re-fires. This cross-story dependency must be documented in Story 3.5 completion notes.

### Migration V6 — correct next version

Current migrations: V1–V5. V6 is the correct next version (`V6__notification_threshold_config.sql`). Confirm by listing `service_webapp/db/migrations/` before writing.

### Kafka topic `notification.events`

Already provisioned with 12 partitions, key=msisdn (ARCH-10, Story 2.1). No topic creation needed. The cdr-pipeline `KafkaProducer` publishes directly — use the existing `publish(topic, key=msisdn, envelope=...)` interface.

### apscheduler version pin

Add `apscheduler>=3.10,<4` to avoid picking up APScheduler 4.x which has a different async API. APScheduler 4.x dropped `AsyncIOScheduler` in favour of a new scheduler class.

## Dev Agent Record

### Implementation Plan

**Task 1: Flyway migration — notification_threshold_config** ✅ (COMPLETED)
- Created V7 migration (not V6, as V6 already exists from Story 3.7)
- Implemented notification_threshold_config table with proper schema
- Applied set_modified_at() trigger using existing V2 function
- Seeded low_balance_threshold_paise=1000 and plan_expiry_reminder_days=3
- Used INSERT ... ON CONFLICT DO NOTHING for idempotency
- Created comprehensive integration tests (7 tests, all passing)
- Fixed trigger naming convention (trg_notification_threshold_config_modified_at)
- Fixed test to use explicit transaction boundaries for proper timestamp testing

**Task 2: cdr-pipeline notification trigger module** (IN PROGRESS)
- Next: Create NotificationTrigger dataclass in cdr-pipeline/src/consumer/notification_trigger.py
- Implement LOW_BALANCE and BALANCE_DEPLETED event publishing
- Add deduplication via _notified set
- Cache threshold from DB at startup

### Completion Notes

**2025-01-09**: Task 1 completed successfully. All acceptance criteria #2, #5, #8 satisfied.

## File List

**New Files:**
- service_webapp/db/migrations/V7__notification_threshold_config.sql
- service_webapp/tests/integration/test_notification_threshold_config.py

## Change Log

**2025-01-09**: Task 1 completed - Flyway migration V7 with notification_threshold_config table and seed data. All integration tests passing (7/7).
