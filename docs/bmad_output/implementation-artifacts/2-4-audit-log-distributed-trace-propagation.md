---
baseline_commit: cbffa4047e63bd4516a3e6431d66fc2821ffbeb1
---
# Story 2.4: Audit Log & Distributed Trace Propagation

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want every billing event written to an immutable audit log and the trace ID propagated across the full CDR → balance → fraud → notification pipeline,
so that every charge is forensically traceable and TRAI 6-year retention is met.

## Acceptance Criteria

1. **Given** a CDR event is processed by the balance engine, **When** the deduction completes, **Then** a row is appended to `billing_audit_log` capturing: `cdr_id`, `subscriber_id`, `event_type`, `charge_paise`, `balance_after_paise`, `trace_id`, and `processed_at` (mapped onto the existing audit-log schema — see Schema Mapping) (FR-59, NFR-4).
2. **And** the `billing_audit_log` table has **no UPDATE or DELETE grants** for the `sboai_app` role — append-only is enforced at the DB layer via a new Flyway migration (FR-59).
3. **And** `trace_id` from the CDR event envelope is included in: the `billing_audit_log` row, the `cdr.enriched.filtered` message header, the `cdr.fraud.flagged` message header, and the `notification.events` message (FR-76, ARCH-11, NFR-17).
4. **And** the OTEL span for the balance deduction references the **same `trace_id`** as the upstream CDR producer span (continuity, not a new root trace).

## Tasks / Subtasks

- [ ] **Task 1: Append-only grants migration** (AC: #2) — the one real new migration
  - [ ] Create `service_webapp/db/migrations/V4__append_only_grants.sql` (next free version; repo has V1/V2/V3). For the three append-only tables — `billing_audit_log`, `billing_cdr_events`, `billing_transactions` — `GRANT INSERT, SELECT` and `REVOKE UPDATE, DELETE` from `sboai_app`. Idempotent/re-runnable (grants are naturally idempotent; guard role existence). The migration runs as `sboai_flyway`. [Source: V1/V2 baseline comments mark these three append-only; 1-2 story (roles sboai_app/sboai_flyway)]
  - [ ] **Coordinate version with Story 2.3:** 2.3 should add no migration; if it does, this becomes `V5`. Whichever lands first takes `V4`. Note the resolution in Completion Notes.
- [ ] **Task 2: Audit writer** (AC: #1) — see Schema Mapping
  - [ ] In `cdr-pipeline` (alongside the balance engine), append a `billing_audit_log` row per completed deduction. Map the AC's logical fields onto the existing columns:
    - `entity_type = 'billing_deduction'`
    - `entity_id = subscriber_id` (UUID)
    - `action = 'DEDUCT'`
    - `actor_type = 'system'`, `actor_id = 'cdr-pipeline'`
    - `new_value` (JSONB) = `{ "cdr_id", "event_type", "charge_paise", "balance_after_paise", "processed_at" }`
    - `correlation_id = trace_id` (W3C trace id stored as UUID — see Schema Mapping)
    - `created_at` = NOW() (the `processed_at`)
  - [ ] Write on the **async/post-deduction** path (never the P95 hot path); batch with the `billing_transactions` ledger inserts from Story 2.3 where possible. Append-only — INSERT only.
- [ ] **Task 3: Trace re-propagation across topics** (AC: #3)
  - [ ] Ensure the producer helper (Story 2.1) stamps `traceparent` header + `trace_id` body on **every** outbound message: `cdr.enriched.filtered` (from 2.2), and the future `cdr.fraud.flagged` / `notification.events` producers. For topics not yet produced in Epic 2 (fraud/notification), add the propagation in the shared producer helper so any future caller inherits it; add a unit test fixing the contract.
- [ ] **Task 4: Span continuity** (AC: #4)
  - [ ] The balance-deduction OTEL span must be created in the context extracted from the incoming Kafka headers (`opentelemetry.propagate.extract`), so its `trace_id` equals the upstream CDR producer's. Assert the deduction span's trace id == the envelope `trace_id`. [Source: 1-4 story (OTEL middleware/propagation); architecture.md#1.13.8]
- [ ] **Task 5: Tests** (AC: #1, #2, #3, #4)
  - [ ] Unit: audit writer builds the correct `billing_audit_log` row (entity_type/action/new_value JSONB keys/correlation_id) from a deduction result.
  - [ ] Unit: producer helper always emits `traceparent` header + body `trace_id`; a message published without a trace_id is rejected/raises (contract test).
  - [ ] Unit: deduction span shares the envelope `trace_id` (extracted context, not a fresh root).
  - [ ] Integration (`@pytest.mark.slow`, testcontainers Postgres): connected as `sboai_app`, an `UPDATE`/`DELETE` on `billing_audit_log` raises an insufficient-privilege error after `V4` runs; an `INSERT` succeeds. Apply migrations via flyway against the test DB. Rootless podman. [Source: 1-2 story (flyway), 1-4 story (testcontainers)]

## Dev Notes

### Scope boundary

- **DOES:** the `V4__append_only_grants.sql` DB-layer immutability migration; the per-deduction `billing_audit_log` append; trace_id propagation guarantees across pipeline topics; OTEL span continuity; the tests proving append-only + trace continuity.
- **DOES NOT:** create/alter billing tables (they exist in V1 — Story 2.3 notes), do balance math (2.3), build fraud/notification producers (Epics 4/6 — only ensure the producer helper propagates trace when they arrive), or the DLQ/admin API (2.5), or S3 archival/pg_partman (Target State, not MVP).

### 🚨 Schema Mapping — there is no `(cdr_id, charge_paise, balance_after_paise, trace_id, processed_at)` audit table

The epic AC lists audit fields as if a bespoke table exists. It does not. `billing_audit_log` (V1 baseline) is a **generic** immutable audit table: `entity_type`, `entity_id`, `action`, `actor_id`, `actor_type`, `old_value JSONB`, `new_value JSONB`, `ip_address INET`, `correlation_id UUID`, `created_at`. Map the AC's logical fields onto it (Task 2). Do **not** add new columns or a new table unless a field genuinely cannot be represented — `new_value` JSONB holds the deduction detail and `correlation_id` holds the trace id. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:237-250]

- **trace_id ↔ correlation_id:** a W3C trace id is 16 bytes = a UUID's width, so it fits `correlation_id UUID`. If the incoming `trace_id` string is a 32-hex-char W3C trace-id, parse it to a UUID for storage; if it is not UUID-coercible, store it as a key inside `new_value` JSONB instead and leave `correlation_id` null. Pick one approach, implement consistently, and document it. (The per-charge numeric ledger — `amount_paise`, `balance_before/after_paise`, `reference_id=cdr_id` — is the Story 2.3 `billing_transactions` row; this story adds the **audit** row.)

### Append-only enforcement is at the DB layer (FR-59, NFR-4)

- The V1/V2 migrations already mark `billing_audit_log`, `billing_cdr_events`, `billing_transactions` as append-only (no `modified_at`, no update trigger). What's missing is the **grant** enforcement so the app role physically cannot UPDATE/DELETE. That is this story's `V4__append_only_grants.sql`. Without it, "append-only" is convention only. [Source: V1 baseline (lines 176, 208-209, 229, 249), V2 trigger comments (lines 3-5, 54); architecture.md#1.8.2 (audit insert-only grants)]
- Roles exist from Story 1.2: `sboai_app` (RW, the app connection), `sboai_readonly`, `sboai_flyway` (runs migrations, has CREATEROLE). Migrations run as `sboai_flyway`; the app connects as `sboai_app`. The REVOKE targets `sboai_app`. [Source: 1-2 story (docker/postgres/init/02_roles.sh)]
- Extensions are created once in `docker/postgres/init/01_extensions.sql` — migrations must NOT `CREATE EXTENSION`. Flyway DDL/grants should be re-run-safe (V2 review lesson: use `DROP ... IF EXISTS` patterns; grants are idempotent). [Source: 1-2 story (init scripts, idempotency patches)]

### TRAI 6-year retention

- MVP requirement is the immutable append-only log; the **6-year + S3-Glacier lifecycle + pg_partman** archival is **Target State**, not MVP scope. Build the immutability now; note retention/archival as future. [Source: architecture.md#1.7.1 (line 378), #1.3.2 (Target State S3/Glacier); epics.md#Story-2.4 (line 944)]

### Trace propagation (FR-76 / NFR-17) — single trace across the pipeline

- One `trace_id` is stamped at CDR ingest and must survive every hop: `cdr.raw` → consumer → `cdr.enriched.filtered` → (Epic 6) `cdr.fraud.flagged` → (Epic 4) `notification.events`, plus the `billing_audit_log` row, plus the OTEL spans. The mechanism is the Story 2.1 producer helper (header `traceparent` + body `trace_id`) and OTEL context extraction on consume. This story's job is to make that propagation **guaranteed and tested**, including for the not-yet-built fraud/notification producers (contract enforced in the helper). [Source: architecture.md#1.11.4 (line 863), #1.13.8 (lines 1606-1608), #1.2.3 (line 74); epics.md#Story-2.4 (line 956)]
- OTEL middleware/propagation was established in Story 1.4 (`service_webapp/src/core/middleware.py`, `request.state.trace_id`, `X-Trace-Id`). The pipeline reuses `opentelemetry.propagate.extract/inject` against Kafka headers. [Source: 1-4 story]

### Depends on Stories 2.1, 2.2, 2.3

- Needs the envelope + producer helper (2.1), the consumer + enriched producer (2.2), and the balance deduction result (2.3) to attach the audit row to. Sequence after them. The audit write and the 2.3 ledger write are naturally co-located on the async path — implement them together if 2.3 and 2.4 are done by the same dev pass, but keep the deliverables (ledger vs audit) distinct.

### PII hygiene

- The audit `new_value` JSONB must not contain raw MSISDN/PII — use `subscriber_id` (UUID), `cdr_id`, amounts. Spans carry no PII attributes. [Source: architecture.md#1.11.6; 1-6 story (audit stores SHA-256/UUIDs, not raw PII)]

### Testing standards summary

- `uv tox` `lint`/`test`. The append-only grant test is the high-value one: as `sboai_app`, UPDATE/DELETE on `billing_audit_log` must fail post-`V4`; INSERT must succeed — run via testcontainers Postgres with flyway-applied migrations, marked `slow`, rootless podman. Unit tests mock db/producer. [Source: 1-2 story, 1-4 story; cdr-pipeline/pyproject.toml]

### Project Structure Notes

- **NEW:** `service_webapp/db/migrations/V4__append_only_grants.sql`; audit-writer module in `cdr-pipeline` (e.g. `src/consumer/audit.py`); tests.
- **MODIFIES:** the Story 2.1 producer helper (assert/guarantee trace propagation), the balance path (attach audit write), `cdr-pipeline/pyproject.toml` if new deps.
- **Migration version:** `V4` (repo has V1/V2/V3). Coordinate with Story 2.3 (which should add none). [Source: service_webapp/db/migrations/]
- **App role:** `sboai_app` (epic's "app_rw" is a naming mismatch).

### References

- [Source: epics.md#Story-2.4 (lines 938-958)]
- [Source: architecture.md#1.7.1 (append-only billing_audit_log, 6-yr retention, line 378), #1.8.2 (audit insert-only grants, line 628)]
- [Source: architecture.md#1.11.4 (traceparent + trace_id, line 863), #1.13.8 (every Kafka msg trace, lines 1606-1608), #1.2.3 (trace CDR→balance→fraud→notification)]
- [Source: architecture.md#1.2.1 (NFR-4 6-yr), #1.3.2 (Target State S3/Glacier archival)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:237-254 (billing_audit_log), V2__modified_at_trigger.sql:3-5,54 (append-only marks)]
- [Source: 1-2 story (roles sboai_app/sboai_flyway, init extensions, migration idempotency), 1-4 story (OTEL middleware/propagation, testcontainers), 1-6 story (audit PII hygiene)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
