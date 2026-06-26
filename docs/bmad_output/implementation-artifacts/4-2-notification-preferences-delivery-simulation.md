---
baseline_commit: b1dda60
---

# Story 4.2: Notification Preferences & Delivery Simulation

Status: review

## Story

As an **authenticated subscriber**,
I want to manage which notification types I receive and have the system respect my preferences,
so that I only receive alerts I've opted into.

## Acceptance Criteria

1. **Given** a subscriber is logged in and navigates to `/subscriber/profile/notifications`, **When** the page loads, **Then** `GET /api/v1/subscriber/notification-preferences` returns their current opt-in status for each type: `LOW_BALANCE`, `BALANCE_DEPLETED`, `PLAN_EXPIRY_REMINDER`, `DATA_NUDGE`. [Source: epics.md:1384]
2. **And** if no preference row exists for a type, the default is opted IN (`is_enabled=true`). [Source: epics.md:1384]
3. **And** the subscriber can toggle each preference on/off; `PATCH /api/v1/subscriber/notification-preferences` persists the change to `notifications_preferences`. [Source: epics.md:1386]
4. **Given** a notification event is consumed from `notification.events`, **When** the notification dispatcher (consumer group `notification-dispatcher`) processes it, **Then** it checks the subscriber's preferences; if `is_enabled=false`, the event is acknowledged and discarded without inserting a delivery record. [Source: epics.md:1392]
5. **And** if `is_enabled=true`, the notification is logged to `notifications_events` with `status='simulated'`, `sent_at=NOW()`, and the original payload. [Source: epics.md:1394]
6. **And** the Notification Portal WebSocket continues to broadcast all events via Story 2.9's existing `notification-portal-broadcaster` consumer — the dispatcher does NOT re-publish; it only logs. [Source: epics.md:1396; main.py lifespan]
7. **Given** the dispatcher encounters a DB failure inserting to `notifications_events`, **When** the error is raised, **Then** it logs the error at ERROR level and acknowledges the Kafka message anyway (no retry loop). [Source: arch reliability pattern]

## Tasks / Subtasks

- [x] **Task 1: Pydantic models** (AC: #1, #3)
  - [x] Create `service_webapp/src/models/notifications.py` (NEW file). Define: `NotificationTypeEnum` (Literal for `LOW_BALANCE`, `BALANCE_DEPLETED`, `PLAN_EXPIRY_REMINDER`, `DATA_NUDGE`). `NotificationPreferenceItem(notification_type: str, is_enabled: bool)`. `NotificationPreferencesResponse(preferences: list[NotificationPreferenceItem])`. `PatchNotificationPreferenceRequest(notification_type: str, is_enabled: bool)`. Suffix `Response`/`Request` per arch §1.11.2. [Source: architecture.md:814]

- [x] **Task 2: DB layer — notifications domain** (AC: #1, #3, #4, #5)
  - [x] Create `service_webapp/src/db/notifications/__init__.py` (empty).
  - [x] Create `service_webapp/src/db/notifications/queries.py`. Function `get_preferences(db: DatabaseProtocol, subscriber_id: str) -> list[dict]` — raw SQL via psycopg3: `SELECT notification_type, is_enabled FROM notifications_preferences WHERE subscriber_id = %s`. Returns list of `{notification_type, is_enabled}` rows. If empty, caller fills defaults. [Source: architecture.md:461; V1:340-352]
  - [x] Create `service_webapp/src/db/notifications/commands.py`. Function `upsert_preference(db: DatabaseProtocol, subscriber_id: str, notification_type: str, is_enabled: bool) -> None` — `INSERT INTO notifications_preferences (id, subscriber_id, notification_type, channel, is_enabled, ...) VALUES (...) ON CONFLICT (subscriber_id, notification_type, channel) DO UPDATE SET is_enabled = EXCLUDED.is_enabled, modified_at = NOW()`. Use `gen_random_uuid()` for id (UUIDv4 — config table, not transactional). Default `channel='push'` for MVP. [Source: V1:340-352; architecture.md:417]
  - [x] Function `insert_notification_event(db: DatabaseProtocol, subscriber_id: str, notification_type: str, channel: str, payload: dict, trace_id: str) -> None` — `INSERT INTO notifications_events (id, subscriber_id, notification_type, channel, status, payload, sent_at, ...) VALUES (uuid_generate_v7(), %s, %s, %s, 'simulated', %s, NOW(), NOW(), NOW())`. Use DB-side `uuid_generate_v7()` to avoid the `uuid_extensions` import (no application-side UUID generation needed here). Payload serialised as `json.dumps(payload)`. [Source: V1:312-325; architecture.md:404]

- [x] **Task 3: Notifications router** (AC: #1, #2, #3)
  - [x] Create `service_webapp/src/routers/notifications.py`. FastAPI `APIRouter(prefix="/api/v1/subscriber", tags=["notifications"])`. Auth: `jwt_payload: dict = require_role("subscriber")` + `subscriber_id = _require_sub(jwt_payload)` (mirror `account.py:217-231`). [Source: core/auth.py:129; account.py:217-231]
  - [x] `GET /notification-preferences`: query `get_preferences(db, subscriber_id)`. Build full list of all 4 types; for types with no DB row, default `is_enabled=True`. Return `success_envelope(NotificationPreferencesResponse(...), trace_id=request.state.trace_id)`. [Source: epics.md:1384; responses.py:21]
  - [x] `PATCH /notification-preferences`: accept `PatchNotificationPreferenceRequest` body. Validate `notification_type` is one of the 4 known types (return 422 on unknown). Call `upsert_preference(...)`. Return 200 `success_envelope({"notification_type": ..., "is_enabled": ...}, ...)`. [Source: epics.md:1386]
  - [x] Wire into `service_webapp/src/main.py` `create_app()` via `app.include_router(notifications_router)`. [Source: main.py:236-238]

- [x] **Task 4: Notification dispatcher consumer** (AC: #4, #5, #6, #7)
  - [x] In `service_webapp/src/main.py` lifespan: create second Kafka consumer `AIOKafkaConsumer("notification.events", group_id="notification-dispatcher", ...)` (mirror the existing `notification-portal-broadcaster` consumer pattern at main.py:157-187). [Source: main.py:157-187]
  - [x] `_dispatch_notification_events()` background task: for each Kafka message, decode `EventEnvelope` JSON, extract `payload["subscriber_id"]` and `payload["notification_type"]`. Query `get_preferences(db, subscriber_id)` for the specific type. If no row or `is_enabled=True`, call `insert_notification_event(...)`. If `is_enabled=False`, log at DEBUG and continue. Commit offset after processing (even on DB error — log at ERROR, do not raise). [Source: epics.md:1388-1394; architecture.md at-least-once delivery note]
  - [x] Acquire the existing `app.state.db` (Postgres pool) inside the task — same pattern as other lifespan consumers use `app.state`. [Source: main.py lifespan]

- [x] **Task 5: Frontend preferences page** (AC: #1, #3)
  - [x] Create `frontend/src/portals/subscriber/NotificationPreferences.tsx` (named export, `readonly Props`, TailwindCSS, <=200 LOC). Route: add `<Route path="profile/notifications">` inside the `/subscriber` `<RoleGuard>` in `App.tsx`. [Source: frontend/CLAUDE.md §2.1, §5.1; App.tsx:40-49]
  - [x] `lib/api.ts`: `getNotificationPreferences()` → `GET /subscriber/notification-preferences`; `patchNotificationPreference(type, enabled)` → `PATCH /subscriber/notification-preferences`. [Source: lib/api.ts pattern]
  - [x] TanStack Query used directly in component — fetch + `useMutation` for patch. Invalidate query on successful patch. [Source: frontend/CLAUDE.md §2.3; queryClient.ts]
  - [x] UI: list of 4 toggle rows (type label + TailwindCSS toggle switch). Optimistic update on toggle. Loading skeleton while fetching. [Source: epics.md:1380-1386]

- [x] **Task 6: Tests** (AC: #1–#7)
  - [x] Backend unit (httpx.AsyncClient, mocked DB): GET returns all 4 types; missing types default to `is_enabled=true`; PATCH upserts correct row; auth matrix (subscriber 200, other role 403, no token 401, sub mismatch 403). [Source: 1-8 story auth matrix]
  - [x] Dispatcher unit (mocked DB): opted-out event → no DB insert; opted-in event → `insert_notification_event` called with correct args; DB failure → ack still committed. [Source: AC #4, #5, #7]
  - [x] One `slow` integration (testcontainers Postgres): real upsert + read cycle for preferences; real insert into `notifications_events` with `status='simulated'`. [Source: 1-4 story testcontainers pattern]
  - [x] Frontend: Vitest + RTL for `NotificationPreferences` (renders 4 rows, toggle fires mutation, loading state). [Source: frontend/CLAUDE.md §7]

## Dev Notes

### Schema — use V1 existing tables, no new migration

Both `notifications_preferences` and `notifications_events` already exist in `V1__baseline_schema.sql`. Do NOT create a new migration for these tables. Story 4.1 creates `V6__notification_threshold_config.sql`; this story only depends on it (for the dispatcher to read preference context), not creates it.

`notifications_preferences` DDL (V1:340-352):
```sql
id                UUID DEFAULT gen_random_uuid() PRIMARY KEY,  -- UUIDv4 (config)
subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
notification_type VARCHAR(50) NOT NULL,
channel           VARCHAR(20) NOT NULL,
is_enabled        BOOL NOT NULL DEFAULT TRUE,
UNIQUE (subscriber_id, notification_type, channel)
```
Use `channel='push'` as the MVP default for all upserts. The `channel` column exists in V1 even though the epic AC omits it — do not try to remove it.

`notifications_events` DDL (V1:312-325):
```sql
id                UUID DEFAULT uuid_generate_v7() PRIMARY KEY,  -- UUIDv7 (transactional)
subscriber_id     UUID NOT NULL REFERENCES identity_subscribers (id),
notification_type VARCHAR(50) NOT NULL,
channel           VARCHAR(20) NOT NULL,
status            VARCHAR(20) NOT NULL DEFAULT 'pending',
payload           JSONB,
sent_at           TIMESTAMPTZ,
```
For simulated delivery: `status='simulated'`, `sent_at=NOW()`, `channel` from event payload or `'sms'` fallback.

### Dispatcher vs WebSocket broadcaster — two consumer groups

Story 2.9 already wired `notification-portal-broadcaster` in `main.py` (main.py:157-187). This story adds `notification-dispatcher` as a completely independent consumer. Both consume `notification.events` topic but with distinct group IDs, so each gets every message independently. The dispatcher does NOT re-publish to WebSocket — that is already handled.

### Default preference — opted IN

When `notifications_preferences` has no row for a given (subscriber_id, notification_type), the semantics are "opted in by default". The GET endpoint must return `is_enabled=true` for missing types. The dispatcher must also treat a missing preference row as "send it" (i.e., call `insert_notification_event`).

### uuid7 in service_webapp

The `uuid7` PyPI package imports as `uuid_extensions` in Python: `from uuid_extensions import uuid7`. This is a known gotcha. However, for `notifications_events.id`, use `uuid_generate_v7()` on the DB side (SQL) rather than generating the UUID in Python — avoids the import entirely. This matches how `billing_transactions` IDs are generated in `balance_writer.py`.

### Auth pattern — owner assertion

Mirror `account.py:217-231` exactly:
```python
def _require_sub(jwt_payload: dict) -> str:
    sub = jwt_payload.get("sub")
    if not sub:
        raise HTTPException(status_code=403, detail="Missing sub in token")
    return sub
```
The subscriber_id used for DB queries must equal `jwt.sub`. Never take subscriber_id from the request body.

### Dispatcher error handling

The dispatcher background task must never crash on a single bad message. Pattern:
1. Decode message — if JSON parse fails, log ERROR + commit offset + continue.
2. DB failure on `insert_notification_event` — log ERROR + commit offset + continue.
3. Never raise from inside the consumer loop; a raised exception kills the task.

### Paise / money

This story does not touch wallet balance. Notification payload may contain `balance_paise` — pass it through as-is to `notifications_events.payload` JSONB. Do not convert.

### MSISDN PII

Log subscriber MSISDN (if present in payload) only as `msisdn[-4:]`. Never log the full MSISDN in the dispatcher. [Source: architecture.md PII policy]

## Completion Notes

Story 4.2 implementation completed successfully on 2026-06-24. All acceptance criteria met:

**Backend Implementation:**
- ✅ Pydantic models created with proper literal types for 4 notification types
- ✅ DB layer implements get_preferences (with defaults), upsert_preference (ON CONFLICT), and insert_notification_event (uuid_generate_v7())
- ✅ GET /notification-preferences returns all 4 types with is_enabled=true default for missing preferences
- ✅ PATCH /notification-preferences validates notification_type and persists changes
- ✅ Notification dispatcher consumer processes events from notification.events topic
- ✅ Dispatcher checks subscriber preferences before inserting notification_events
- ✅ Opted-out events are discarded (DEBUG log) without DB insert
- ✅ Opted-in events are logged to notifications_events with status='simulated'
- ✅ Dispatcher handles DB failures gracefully (ERROR log + commit offset, no crash)
- ✅ Router wired into main.py with proper auth matrix (subscriber 200, other roles 403, no token 401)

**Frontend Implementation:**
- ✅ NotificationPreferences.tsx component with TailwindCSS toggle switches
- ✅ API functions added to lib/api.ts (getNotificationPreferences, patchNotificationPreference)
- ✅ TanStack Query integration with useMutation for updates
- ✅ Route added at /subscriber/profile/notifications
- ✅ Loading skeleton while fetching preferences
- ✅ Error state handling with user-friendly messages

**Test Coverage:**
- ✅ 27 backend unit tests (9 models + 6 DB + 8 router + 4 dispatcher)
- ✅ 6 frontend component tests (RTL + Vitest)
- ✅ 2 integration tests (testcontainers Postgres)
- ✅ All tests pass successfully
- ✅ Auth matrix fully tested
- ✅ Default preference behavior verified
- ✅ Error handling validated

**Technical Notes:**
- Used DB-side uuid_generate_v7() to avoid uuid_extensions import
- Implemented proper owner assertion via _require_sub()
- Channel defaults to 'push' for MVP
- Dispatcher is independent consumer (notification-dispatcher group ID)
- No new migrations needed - uses existing V1 tables
- PII handling: logs only last 4 digits of MSISDN

**Files Modified:**
- service_webapp/src/models/notifications.py (NEW)
- service_webapp/src/models/__init__.py (updated exports)
- service_webapp/src/db/notifications/__init__.py (NEW)
- service_webapp/src/db/notifications/queries.py (NEW)
- service_webapp/src/db/notifications/commands.py (NEW)
- service_webapp/src/routers/notifications.py (NEW)
- service_webapp/src/main.py (added dispatcher consumer and router)
- service_webapp/tests/unit/test_notifications_models.py (NEW)
- service_webapp/tests/unit/test_notifications_db.py (NEW)
- service_webapp/tests/unit/test_notifications_router.py (NEW)
- service_webapp/tests/unit/test_notification_dispatcher.py (NEW)
- service_webapp/tests/integration/test_notifications_integration.py (NEW)
- frontend/src/lib/api.ts (added notification preference endpoints)
- frontend/src/portals/subscriber/NotificationPreferences.tsx (NEW)
- frontend/src/portals/subscriber/NotificationPreferences.test.tsx (NEW)
- frontend/src/App.tsx (added route)

Story is ready for code review. All acceptance criteria satisfied, comprehensive test coverage in place.
