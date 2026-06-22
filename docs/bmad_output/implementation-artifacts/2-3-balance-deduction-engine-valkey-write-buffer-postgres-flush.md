---
baseline_commit: cf7ecad14fddcdaca6a98a9fc0a1780df68f8ba3
---

# Story 2.3: Balance Deduction Engine — Valkey Write Buffer & Postgres Flush

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want the balance deduction engine to atomically deduct charges from a Valkey write buffer and periodically flush to Postgres, meeting the P95 ≤ 200ms latency target,
so that balance deductions are fast, idempotent, and durable.

## Acceptance Criteria

1. **Given** a validated CDR event arrives from `cdr.enriched.filtered`, **When** the balance engine processes it, **Then** the charge amount is deducted from `balance:{msisdn}` in Valkey using `INCRBY` (negative value) within **P95 ≤ 200ms** measured from CDR receipt (FR-58, NFR-1).
2. **And** the deduction is **idempotent**: a second CDR with the same `cdr_id` returns without modifying the balance (NFR-9) — reusing the `dedup:{cdr_id}` guard from Story 2.2; the balance engine must not double-apply on re-delivery.
3. **And** the updated balance is flushed to the `billing_wallet_balances` table in Postgres via async **bulk upsert** on a configurable interval (default: **every 2s or 5,000 changed keys, whichever comes first**).
4. **And** `balance:{msisdn}` keys are **never evicted** (Valkey `maxmemory-policy noeviction`) and have **no TTL** (ARCH-5, ARCH-6).
5. **And** on cdr-pipeline restart, `load_balances_from_postgres()` re-seeds all `balance:{msisdn}` keys from `billing_wallet_balances.balance_paise` **before** the consumer loop starts (ARCH-6).
6. **And** the per-deduction forensic detail (cdr_id, charge, before/after balance) is recorded — see Schema Reconciliation; no `V*__billing_schema.sql` is created because the billing tables already exist in the V1 baseline.
7. **And** talktime deduction uses the per-second voice rate from the subscriber's active plan; an unlimited-bundle deduction logs the event with **zero charge**.

## Tasks / Subtasks

- [ ] **Task 1: Balance writer (hot path)** (AC: #1, #2, #4)
  - [ ] `cdr-pipeline/src/consumer/balance_writer.py` — `async deduct(cache, *, msisdn, cost_paise, cdr_id)`: idempotency already enforced by Story 2.2's dedup guard (first-sight only), then `INCRBY balance:{msisdn} -cost_paise` (atomic). Key domain `balance:{msisdn}`, **no TTL**. Mark the `msisdn` "dirty" in an in-process set/dict for the flusher. Keep this call O(1) and off any blocking I/O — it is the P95 path.
  - [ ] Wire it into the Story 2.2 batch processor's balance hook (the seam left by 2.2). Deduction runs only on first-sight events.
- [ ] **Task 2: Rating / charge calculation** (AC: #7)
  - [ ] `cdr-pipeline/src/consumer/rating.py` — compute `cost_paise` from the CDR + the subscriber's **active plan** (`plans_plans` joined via the subscriber's plan assignment). Voice: per-second rate × `duration_seconds`. SMS/data per the plan's bundle rules. **Unlimited bundle** (plan grants unmetered usage for that `cdr_type`): record the event with `cost_paise = 0` (still deduct 0, still audit). Cache plan rates in-process (plans are a small, low-churn reference table) to protect P95.
  - [ ] If the incoming CDR already carries a non-null `cost_paise` (pre-rated upstream), honour it and skip recomputation; document which mode the simulator (Story 2.8) uses. Resolve ambiguity in Completion Notes.
- [ ] **Task 3: Startup balance warm-up** (AC: #5)
  - [ ] `cdr-pipeline/src/consumer/startup.py` — `async load_balances_from_postgres(db, cache)`: bulk-read `SELECT msisdn, balance_paise FROM billing_wallet_balances` and `SET balance:{msisdn} <balance_paise>` for each via a Valkey pipeline. Must complete in < 5s for 300K rows. Call it from `main.py` **before** starting the consumer loop. [Source: architecture.md#1.7.3 (load_balances_from_postgres)]
- [ ] **Task 4: Async Postgres flusher** (AC: #3)
  - [ ] `cdr-pipeline/src/adapters/postgres.py` — `Psycopg3AsyncAdapter` over `psycopg_pool.AsyncConnectionPool` (mirror `service_webapp/src/adapters/postgres.py`), connecting as `sboai_app` (`settings.db`).
  - [ ] A background flush task reads the dirty `msisdn` set, reads current `balance:{msisdn}` values from Valkey, and **bulk-upserts** into `billing_wallet_balances` (`INSERT ... ON CONFLICT (msisdn) DO UPDATE SET balance_paise=EXCLUDED.balance_paise, last_deduction_at=NOW()`). Trigger on 2s **or** 5,000 dirty keys. Keys are **not** deleted after flush (they remain the live buffer). On shutdown, flush once more. [Source: architecture.md#1.7.3 (flush every 2s/5K), #1.4.1]
- [ ] **Task 5: Per-deduction ledger row** (AC: #6) — see Schema Reconciliation
  - [ ] On each first-sight deduction, append a `billing_transactions` row: `transaction_type='cdr_deduction'`, `amount_paise = -cost_paise`, `reference_type='cdr'`, `reference_id = cdr_id`, `balance_before_paise`, `balance_after_paise`, `description` (e.g. cdr_type). This is the append-only forensic ledger; do it on the async (flush-adjacent) path, NOT in the P95 hot path — batch these inserts. (The immutable `billing_audit_log` row + trace_id is Story 2.4.)
- [ ] **Task 6: Latency instrumentation** (AC: #1)
  - [ ] Emit an OTEL span / metric for "balance deduction" timing from CDR receipt to `INCRBY` completion, so P95 ≤ 200ms is observable. Span references the upstream CDR `trace_id` (full trace assertion is Story 2.4). [Source: architecture.md#1.4.3 (P95 200ms, Valkey write path)]
- [ ] **Task 7: Tests** (AC: #1, #2, #3, #5, #7)
  - [ ] Unit: `deduct` issues `INCRBY balance:{msisdn} -cost`; a re-delivered `cdr_id` (already deduped) does not deduct again.
  - [ ] Unit: rating computes voice per-second charge from a plan; unlimited bundle → `cost_paise == 0` still logged.
  - [ ] Unit: flusher triggers at 2s and at 5K dirty keys; bulk upsert SQL uses `ON CONFLICT (msisdn)`; keys not deleted post-flush.
  - [ ] Integration (`@pytest.mark.slow`, testcontainers Postgres + Valkey): warm-up seeds keys from `billing_wallet_balances`; deduct; flush; assert Postgres `balance_paise` matches Valkey; a `billing_transactions` ledger row exists with correct before/after. Rootless podman.

## Dev Notes

### Scope boundary

- **DOES:** Valkey `INCRBY` deduction on `balance:{msisdn}`, plan-based rating (incl. unlimited→0), startup warm-up from Postgres, async bulk-upsert flusher to `billing_wallet_balances`, append-only `billing_transactions` ledger rows, P95 instrumentation. Unit + one integration test.
- **DOES NOT:** the immutable `billing_audit_log` row + cross-pipeline trace_id assertions (Story 2.4), DB append-only **grants** migration (Story 2.4), DLQ/admin endpoints (2.5), recharge top-ups (Epic 3). Consumes `cdr.enriched.filtered` produced by Story 2.2.

### 🚨 Schema Reconciliation — the most important correction (read first)

The epic AC says: *"a Flyway migration (V5__billing_schema.sql) creates: wallet_balance, billing_audit_log, cdr_dedup."* **This is outdated and must NOT be followed literally.** The actual repo already has these tables in the V1 baseline:

- **`billing_wallet_balances`** (V1, lines 162-173): `id UUID`, `subscriber_id`, `msisdn VARCHAR(15)` (UNIQUE), `balance_paise BIGINT`, `last_recharge_at`, `last_deduction_at`, `created_at`, `modified_at`. Has the V2 `modified_at` trigger. → **Flush target.** (The epic's `wallet_balance(msisdn, balance_paise, updated_at)` = this table; column is `modified_at`, not `updated_at`.)
- **`billing_transactions`** (V1, lines 218-230): append-only ledger with `transaction_type`, `amount_paise BIGINT`, `reference_type`, `reference_id UUID`, `balance_before_paise`, `balance_after_paise`, `created_at`. → **Per-deduction forensic ledger** (the epic's "charge_paise, balance_after_paise" detail lives here as `amount_paise` + `balance_after_paise`).
- **`billing_audit_log`** (V1, lines 237-250): generic immutable audit (`entity_type`, `entity_id`, `action`, `old_value`/`new_value JSONB`, `correlation_id UUID`, `created_at`). → used by **Story 2.4** for the audit event + trace_id; do not change its schema.
- **`billing_cdr_events`** (V1, lines 177-209): full CDR persistence (Story 2.6/simulator territory; this story does not need to insert CDR rows unless rating requires it — prefer not to on the hot path).
- **`cdr_dedup`: does NOT exist and must NOT be created.** Dedup is Valkey-only (`dedup:{cdr_id}`, 24h). [Source: architecture.md#1.7.3]

**Therefore this story creates NO new migration.** The tables and columns it needs already exist. If you find a genuinely missing column, add it as `V4__...` (next free version), coordinating with Story 2.4 (which also adds a V4 grants migration — if both land, sequence them V4/V5 and note it). Prefer using the existing columns. [Source: service_webapp/db/migrations/V1__baseline_schema.sql:157-254; V2__modified_at_trigger.sql]

### P95 ≤ 200ms — keep agents and Postgres off the hot path (NFR-1, ARCH-6)

- The hot path is: receive CDR → (dedup, done in 2.2) → rate (in-process plan cache) → `INCRBY balance:{msisdn}`. Everything else — Postgres upsert, ledger inserts, fraud/notification — is async/post-deduction and must never block the deduction. [Source: architecture.md#1.4.3 (line 194), #1.2.3 (agents off hot path)]
- `balance:{msisdn}` is a STRING integer (paise), `INCRBY -cost`, **no TTL** (persistent running counter), requires `noeviction`. 300K subs × ~50 bytes ≈ 15MB. [Source: architecture.md#1.7.3 (ARCH-5/ARCH-6, line 492)]

### Money is paise (integer) everywhere

- All balances/charges are `BIGINT` paise — never floats. `balance_paise`, `amount_paise`, `cost_paise` are all integer paise. Avoids float precision bugs. [Source: architecture.md#1.12.2 (line 1233); V1 baseline column types]

### Idempotency relationship with Story 2.2

- Story 2.2's `dedup:{cdr_id}` SET NX already guarantees a given `cdr_id` is processed once. The balance engine runs **only on first-sight events**, so deduction is idempotent by construction. Do not add a second dedup mechanism; rely on the 2.2 guard and ensure the balance hook is invoked only on the first-sight branch. [Source: epics.md#Story-2.3 (line 924); architecture.md#1.7.3]

### Warm-up ordering (ARCH-6)

- `load_balances_from_postgres()` MUST finish before the consumer starts deducting — otherwise an `INCRBY` on a missing key starts from 0 and corrupts the balance. Sequence in `main.py`: build adapters → warm-up → start consumer pool. Warm-up uses a Valkey pipeline for the bulk `SET`. [Source: architecture.md#1.7.3 (line 493); epics.md#Story-2.3 (line 930)]

### Rating / plan data

- Plans live in `plans_plans` (V1 baseline, reference table). Subscriber→plan assignment is via the identity/plan tables. Voice per-second rate derives from the plan's voice bundle/price; unlimited bundles → 0 charge but still logged. Cache plan rates in-process. The exact plan↔subscriber join columns are in the baseline schema — read `V1__baseline_schema.sql` (identity_/plans_ sections) before implementing. [Source: architecture.md#1.12.2 (plan fields); V1 baseline]
- If rating proves underspecified at implementation time, implement the documented voice per-second + unlimited-zero rule, leave SMS/data rating with a clearly-marked simple default, and record the assumption in Completion Notes (don't silently guess complex tariffs).

### Async adapters & deps

- `psycopg[async,pool]>=3.2`, `valkey[asyncio]>=6` — add to `cdr-pipeline/pyproject.toml` runtime + tox env `deps`. Connect as `sboai_app` (`settings.db`). Mirror `service_webapp/src/adapters/postgres.py` for the pool/lifespan pattern. `DatabaseProtocol`/`CacheProtocol` in `core/protocols/`. [Source: service_webapp/src/adapters (pool pattern); architecture.md#1.12.1 (ARCH-15)]

### PII hygiene

- `msisdn` is PII. Logs/spans use `subscriber_id` (UUID) or masked `msisdn[-4:]`; never the full number. [Source: architecture.md#1.11.6; 1-6 story]

### Testing standards summary

- `uv tox` `lint`/`test`; unit tests mock cache/db (fast); one `slow` testcontainers integration (Postgres + Valkey) under rootless podman. P95 timing is asserted structurally (span emitted), not as a perf benchmark in CI. Add new imports to tox env `deps`. [Source: cdr-pipeline/pyproject.toml; 1-4 story]

### Project Structure Notes

- **NEW:** `cdr-pipeline/src/consumer/{balance_writer,rating,startup}.py`, `cdr-pipeline/src/adapters/postgres.py`, `cdr-pipeline/src/core/protocols/db.py`, tests.
- **MODIFIES:** `cdr-pipeline/src/main.py` (add warm-up + flusher startup; the consumer loop from 2.2), `cdr-pipeline/pyproject.toml` (psycopg/valkey deps).
- **NO new Flyway migration** (see Schema Reconciliation). If unavoidable, it is `V4` (coordinate with Story 2.4).
- **App role:** `sboai_app` (the epic's "app_rw" is a naming mismatch). [Source: 1-2 story (roles)]

### References

- [Source: epics.md#Story-2.3 (lines 908-934)]
- [Source: architecture.md#1.7.3 (ARCH-5/ARCH-6: balance:{msisdn} no-TTL noeviction, INCRBY, load_balances_from_postgres, flush 2s/5K, lines 482-509)]
- [Source: architecture.md#1.4.1 (consumer/flush), #1.4.3 (P95 ≤ 200ms, agents off hot path, lines 193-195)]
- [Source: architecture.md#1.2.1 (NFR-1 200ms, NFR-9 idempotency), #1.12.2 (paise integer)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:157-254 (billing tables), V2__modified_at_trigger.sql]
- [Source: service_webapp/src/adapters/postgres.py + redis.py (adapter patterns)]
- [Source: cdr-pipeline/src/core/config.py, pyproject.toml]
- [Source: 1-2 story (roles, valkey config), 1-4 story (testcontainers), 1-6 story (PII)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
