---
baseline_commit: 89d48fe
---

# Story 6.6: Account Takeover Prevention — Blacklist, Cognito Disable & JWT Revocation

Status: ready-for-dev

## Story

As a **platform engineer**,
I want confirmed SIM swap fraud to automatically blacklist the subscriber, disable their Cognito account, and revoke active JWTs,
so that a compromised account is locked down immediately without manual intervention.

## Acceptance Criteria

1. **Given** the Fraud Detection Agent verdict = `confirmed_fraud` AND rule_triggered = `SIM_SWAP`, **When** the account protection workflow runs, **Then** a row is inserted into `fraud_blacklist`: subscriber_id, msisdn, blacklisted_at, reason = `'SIM_SWAP_CONFIRMED'`, blacklisted_by = `'fraud_agent'`. (FR-66, ARCH-33) [Source: epics.md:1934]
2. **And** the MiniStack Cognito admin API is called to disable the subscriber's user account. (ARCH-33) [Source: epics.md:1936]
3. **And** all the subscriber's active tokens are revoked via the Cognito admin API (token revocation) — JWTs are stateless, so there is no `auth_sessions` table; the 30-minute access-token TTL bounds the residual validity window. (architecture §1.8.1/§1.8.2, ARCH-33) [Source: epics.md:1938]
4. **And** subsequent JWT validation for this subscriber returns HTTP 401 — the FastAPI JWT middleware checks `fraud_blacklist` on every request for subscribers with active fraud cases. [Source: epics.md:1940]
5. **And** the account protection actions are recorded in `audit_log` with event_type = `'ACCOUNT_TAKEOVER_PREVENTION'`. [Source: epics.md:1942]
6. **And** a Flyway migration creates: `fraud_blacklist` table (blacklist_id UUIDv7, subscriber_id, msisdn, blacklisted_at, reason, blacklisted_by). [Source: epics.md:1944]

## Tasks / Subtasks

- [ ] **Task 1: Flyway migration V13 — fraud_blacklist columns** (AC: #1, #6)
  - [ ] Create `service_webapp/db/migrations/V13__fraud_blacklist_ato.sql`.
  - [ ] Version: V11 (6.2 fraud_pre_screener), V12 (6.3 fraud_cases_extensions); this is V13. Renumber only if a lower version is free — never collide with V10 (usage MV).
  - [ ] `fraud_blacklist` already exists in V1 (`id UUIDv7, subscriber_id NOT NULL UNIQUE, reason TEXT, fraud_case_id FK, blacklisted_at, created_at, modified_at`). AC mappings (audit 2026-06-25 confirms all columns unused outside DDL): `blacklist_id`→`id`; `subscriber_id` exists; `blacklisted_at` exists; `reason` exists. ADD the two missing: `msisdn`, `blacklisted_by`.
  - [ ] SQL (additive only):
    ```sql
    ALTER TABLE fraud_blacklist
        ADD COLUMN IF NOT EXISTS msisdn         VARCHAR(15),
        ADD COLUMN IF NOT EXISTS blacklisted_by VARCHAR(50) DEFAULT 'fraud_agent';
    CREATE INDEX IF NOT EXISTS idx_fraud_blacklist_msisdn ON fraud_blacklist (msisdn);
    ```
  - [ ] `subscriber_id` is already `NOT NULL UNIQUE` (one blacklist row per subscriber — the ATO re-run for an already-blacklisted subscriber must be idempotent; see dev notes).

- [ ] **Task 2: Cognito adapter — admin disable + global sign-out** (AC: #2, #3)
  - [ ] In `service_webapp/src/adapters/cognito.py`, extend the `CognitoProvider` Protocol + `MinistackCognitoProvider` + the Fake/test impl with two methods:
    - `async def admin_disable_user(self, username: str) -> None` — calls `cognito-idp:AdminDisableUser` via `asyncio.to_thread` (existing boto3 lazy client pattern). Maps the subscriber's `cognito_user_id` (from `identity_subscribers`) to the Cognito `Username`.
    - `async def admin_user_global_sign_out(self, username: str) -> None` — calls `cognito-idp:AdminUserGlobalSignOut` (revokes all refresh tokens / active sessions). This is the "token revocation" — JWTs are stateless, so this invalidates refresh tokens and new access-token refreshes fail; existing 30-min access tokens expire by TTL (§1.8.1).
  - [ ] Reuse the existing lazy `boto3.client("cognito-idp", endpoint_url=settings.cognito_endpoint_url)` + `asyncio.to_thread` wrapping (do NOT make blocking boto3 calls on the event loop). [Source: adapters/cognito.py; ARCH-15 async]

- [ ] **Task 3: Account protection workflow** (AC: #1, #2, #3, #5)
  - [ ] Create `service_webapp/src/agents/fraud/takeover.py` exposing `async def apply_account_protection(*, subscriber_id, msisdn, fraud_case_id, trace_id) -> None`. Called from the 6.3 consumer's branch when `verdict == confirmed_fraud and fraud_type == 'SIM_SWAP'`.
  - [ ] Steps (all inside the workflow, best-effort + audited):
    1. `blacklist_subscriber(conn, subscriber_id, msisdn, fraud_case_id, reason='SIM_SWAP_CONFIRMED', blacklisted_by='fraud_agent')` — INSERT into fraud_blacklist. Idempotent: `ON CONFLICT (subscriber_id) DO UPDATE SET reason=EXCLUDED.reason, blacklisted_by=EXCLUDED.blacklisted_by, blacklisted_at=NOW()` (re-running ATO for an already-blacklisted subscriber refreshes the row, not an error).
    2. Resolve `cognito_user_id` from `identity_subscribers`; call `await cognito.admin_disable_user(cognito_user_id)`.
    3. `await cognito.admin_user_global_sign_out(cognito_user_id)` (revoke).
    4. Write ONE audit row (see dev notes for the billing_audit_log mapping).
  - [ ] Order + resilience: blacklist FIRST (so the 401 enforcement is live even if Cognito is slow/unavailable), then disable, then sign-out, then audit. Wrap each Cognito call so a Cognito outage still leaves the subscriber blacklisted (the middleware 401 is the local enforcement backstop per ARCH-33). Log failures; do NOT raise out of the consumer (the fraud_case is already OPEN).

- [ ] **Task 4: fraud db commands + audit** (AC: #1, #5)
  - [ ] In `service_webapp/src/db/fraud/commands.py` (from 6.3):
    - `blacklist_subscriber(conn, *, subscriber_id, msisdn, fraud_case_id, reason, blacklisted_by) -> None` — the idempotent INSERT/UPSERT above.
    - `record_ato_audit(conn, *, subscriber_id, msisdn, fraud_case_id, trace_id, actions: list[str]) -> None` — INSERT into `billing_audit_log` (the canonical append-only audit table; epics says `audit_log` but the real table is `billing_audit_log`):
      ```sql
      INSERT INTO billing_audit_log
        (entity_type, entity_id, action, actor_id, actor_type, new_value, correlation_id)
      VALUES
        ('subscriber', %(subscriber_id)s, 'BLACKLIST', 'fraud_agent', 'fraud_agent',
         jsonb_build_object(
           'event_type', 'ACCOUNT_TAKEOVER_PREVENTION',
           'msisdn', %(msisdn_masked)s,
           'fraud_case_id', %(fraud_case_id)s,
           'reason', 'SIM_SWAP_CONFIRMED',
           'actions', %(actions)s::jsonb),
         %(trace_id)s)
      ```
      `action` is VARCHAR(20) — `'BLACKLIST'` fits (9 chars); the full AC `event_type='ACCOUNT_TAKEOVER_PREVENTION'` goes in `new_value.event_type` (it is 26 chars, does NOT fit `action`). [Source: V1__baseline_schema.sql billing_audit_log DDL; audit 2026-06-25]
  - [ ] In `queries.py`: `is_subscriber_blacklisted(conn, subscriber_id: UUID) -> bool` — `SELECT EXISTS(SELECT 1 FROM fraud_blacklist WHERE subscriber_id=%s)`.

- [ ] **Task 5: JWT middleware blacklist check → 401** (AC: #4)
  - [ ] In `service_webapp/src/core/auth.py` `require_role` (and/or `SupportIdentityMiddleware.dispatch`), after `validator.decode(token)` succeeds, resolve the subscriber (`sub` claim → `subscriber_id`) and check `is_subscriber_blacklisted`. If blacklisted → raise `UnauthenticatedError` → HTTP 401.
  - [ ] No Redis cache — direct Postgres lookup on the UNIQUE-indexed `fraud_blacklist.subscriber_id` (architecture.md#1.7.3 explicitly eliminates the Redis enforcement cache; Cognito + the 30-min TTL are the real enforcement, the middleware check is the MVP-local backstop since there is no API Gateway in MVP). [Source: architecture.md#1.7.3, §1.8.2; ARCH-33]
  - [ ] Bound the DB hit: the check is a single indexed EXISTS by subscriber_id. Keep it unconditional (AC says "every request for subscribers with active fraud cases"); the UNIQUE index makes it O(1).

- [ ] **Task 6: Wire into the 6.3 consumer** (AC: #1)
  - [ ] In the 6.3 fraud consumer, after `create_fraud_case`, branch: if `verdict == 'confirmed_fraud' and fraud_type == 'SIM_SWAP'`: `await apply_account_protection(subscriber_id, msisdn, case_id, trace_id)`. Do NOT block on it failing the case creation (fire-and-audit). [Source: 6-3 Task 4 consumer branching]

- [ ] **Task 7: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_takeover_workflow.py` (Fake Cognito + mocked conn): confirmed SIM_SWAP → blacklist row inserted with reason/blacklisted_by; `admin_disable_user` + `admin_user_global_sign_out` each called once; audit row written with `new_value.event_type='ACCOUNT_TAKEOVER_PREVENTION'`; idempotent re-run → upsert, Cognito called again, no duplicate PK error.
  - [ ] `service_webapp/tests/unit/test_blacklist_check.py`: `is_subscriber_blacklisted` True/False; middleware/`require_role` returns 401 for blacklisted subscriber with otherwise-valid token; non-blacklisted → request proceeds.
  - [ ] `service_webapp/tests/unit/test_cognito_admin_methods.py`: Fake records `admin_disable_user` / `admin_user_global_sign_out` calls; Ministack impl wraps boto3 via `asyncio.to_thread` (monkeypatch boto3 client).
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1+V11+V12+V13); seed a SIM_SWAP confirmed_fraud case → assert fraud_blacklist row + billing_audit_log row; subsequent `require_role` for that subscriber → 401.

## Dev Notes

### fraud_blacklist — only 2 columns missing

V1 `fraud_blacklist`: `id, subscriber_id (NOT NULL UNIQUE), reason TEXT, fraud_case_id FK, blacklisted_at, created_at, modified_at`. AC needs `msisdn` and `blacklisted_by` — both ADDITIVE. Everything else reuses (`blacklist_id`→`id`, `subscriber_id`, `reason`, `blacklisted_at`). Audit confirms the table is unused outside DDL → safe additions. [Source: V1__baseline_schema.sql:443-455; audit 2026-06-25]

### subscriber_id UNIQUE — ATO must be idempotent

`fraud_blacklist.subscriber_id` is `NOT NULL UNIQUE` (one row per subscriber, no history). A confirmed SIM_SWAP case may be reprocessed (at-least-once consumer), or a second confirmed case may arrive. The blacklist INSERT MUST be an UPSERT (`ON CONFLICT (subscriber_id) DO UPDATE`) — a plain INSERT would violate the UNIQUE constraint on replay. Cognito disable/sign-out are already idempotent (disabling a disabled user is a no-op; global sign-out of a signed-out user is a no-op). [Source: V1 UNIQUE constraint; at-least-once replay concern; 6-3 consumer dedup]

### billing_audit_log mapping — action VARCHAR(20) constraint

`billing_audit_log.action` is `VARCHAR(20)`. `ACCOUNT_TAKEOVER_PREVENTION` is 26 chars — does NOT fit. Do NOT widen the shared column. Map: `action='BLACKLIST'` (9 chars), `actor_type='fraud_agent'` (12 chars, fits VARCHAR(20)), and put the full `event_type='ACCOUNT_TAKEOVER_PREVENTION'` inside `new_value` JSONB. `entity_type='subscriber'`, `entity_id=subscriber_id`, `correlation_id=trace_id`. This is the canonical append-only audit table (epics says `audit_log`; the real name is `billing_audit_log`). [Source: V1__baseline_schema.sql:237-251 billing_audit_log DDL; audit 2026-06-25]

### Cognito is the real enforcement; middleware is the MVP-local backstop

architecture.md §1.8.2/ARCH-33: "subsequent JWT validation at API Gateway fails". There is NO API Gateway in the MVP — so the FastAPI `require_role`/middleware performs the blacklist check locally and returns 401. This is an explicit MVP addition beyond the Target-State story. No Redis cache (architecture.md#1.7.3 eliminates it) — direct Postgres EXISTS on the UNIQUE index. The 30-min access-token TTL (§1.8.1) bounds residual validity; `AdminUserGlobalSignOut` revokes refresh tokens so no new access tokens can be minted. [Source: architecture.md §1.8.1, §1.8.2, #1.7.3; ARCH-33]

### boto3 must stay off the event loop

`MinistackCognitoProvider` already wraps boto3 calls in `asyncio.to_thread` (ARCH-15). The new `admin_disable_user` / `admin_user_global_sign_out` MUST follow the same pattern — never call boto3 synchronously on the asyncio loop. Resolve `cognito_user_id` from `identity_subscribers` (NOT trusted from the client). [Source: adapters/cognito.py; ARCH-15; 6-3 IDOR-safe resolution]

### Trigger condition — confirmed_fraud AND SIM_SWAP only

ATO runs ONLY when `verdict == 'confirmed_fraud' AND fraud_type == 'SIM_SWAP'`. Velocity / suspicious-recharge / geo confirmed cases do NOT blacklist/disable (they are fraud, but not account-takeover). This is the AC #1 gate. The check lives in the 6.3 consumer branch. [Source: epics.md:1930]

### Audit must not raise out of the consumer

`apply_account_protection` is best-effort: blacklist is the hard requirement (local 401); Cognito disable/sign-out are best-effort (log + continue on failure — the blacklist + TTL still lock the account). The fraud_case is already OPEN; a Cognito outage must not crash the fraud consumer. Audit write failures SHOULD surface (log ERROR) but not block. [Source: ARCH-33 resilience; architecture.md#1.13.5 async accepted gap]

### Project Structure Notes

- New migration: `service_webapp/db/migrations/V13__fraud_blacklist_ato.sql` (msisdn + blacklisted_by on fraud_blacklist)
- Extended adapter: `service_webapp/src/adapters/cognito.py` (admin_disable_user, admin_user_global_sign_out on Protocol + Ministack + Fake)
- New module: `service_webapp/src/agents/fraud/takeover.py` (apply_account_protection)
- Extended db: `service_webapp/src/db/fraud/{queries.py,commands.py}` (blacklist_subscriber, record_ato_audit, is_subscriber_blacklisted)
- Extended auth: `service_webapp/src/core/auth.py` (blacklist check → 401) and/or `core/middleware.py`
- Extended consumer: 6.3's fraud consumer branch (call apply_account_protection)
- New tests: `tests/unit/test_takeover_workflow.py`, `test_blacklist_check.py`, `test_cognito_admin_methods.py`; `tests/integration/test_account_takeover.py`
- No frontend. No cdr-pipeline changes. (cdr-pipeline owns the screener; ATO is a service_webapp enforcement concern.)

### References

- [Source: epics.md:1920-1944 — Story 6.6 acceptance criteria]
- [Source: epics.md#1.2.3 ARCH-33 — account takeover (blacklist + Cognito disable + revoke + 401)]
- [Source: epics.md#1.2.2 FR-66 — account takeover prevention]
- [Source: architecture.md §1.8.1 — 30-min access-token TTL; §1.8.2 — ATO controls; #1.7.3 — no Redis blacklist cache]
- [Source: V1__baseline_schema.sql:237-251 — billing_audit_log (action VARCHAR(20)); 443-455 — fraud_blacklist]
- [Source: audit 2026-06-25 — fraud_blacklist columns unused; billing_audit_log action width; no event_type column]
- [Source: service_webapp/src/adapters/cognito.py — MinistackCognitoProvider boto3+to_thread pattern]
- [Source: service_webapp/src/core/auth.py — require_role; core/middleware.py — SupportIdentityMiddleware]
- [Source: 6-3-fraud-detection-agent-llm-powered-risk-analysis.md — consumer branch, confirmed_fraud+SIM_SWAP]
- [Source: deferred-work.md — require_role built but unwired; cognito:groups; JWT 30-min TTL]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
