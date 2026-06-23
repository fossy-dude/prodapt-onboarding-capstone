---
baseline_commit: cf7ecad14fddcdaca6a98a9fc0a1780df68f8ba3
---

# Story 2.3: Balance Deduction Engine — Valkey Write Buffer & Postgres Flush

Status: in-progress

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

Claude (Sonnet-class) via `/bmad-dev-story` workflow.

### Debug Log References

- **Bugs caught by inspection (tests not executed — see Verification Pending):**
  1. `BalanceEngine` was a `@dataclass` with a hand-written `__init__`; a manual `__init__` on a dataclass silently skips the `field(default_factory=...)` defaults, so `_dirty_msisdns` / `_ledger_queue` / indices were never set → `AttributeError`. Fixed by making `BalanceEngine` a plain class that initialises all in-process state in `__init__`.
  2. `stop()` cancelled the flusher task then `await self._flusher_stopped.wait()` — cancellation meant the loop's `.set()` could never run → hang. Rewrote `stop()` to clear `_flusher_running`, await the task with a timeout backstop, then do a final drain flush.
  3. `transaction` on `DatabaseProtocol` / `Psycopg3AsyncAdapter` was decorated `@property @asynccontextmanager`, but the call site is `async with db.transaction() as conn` (a call). `@property` made `transaction()` non-callable. Removed `@property`; `transaction` is now a plain `@asynccontextmanager` method (mirrors `service_webapp`).
  4. psycopg3 `execute(query, params=None)` takes a single `params` sequence; `_flush` (and the integration seed inserts/SELECTs) passed params as spread positional args → `TypeError`. Fixed to pass tuples.
  5. Original unit tests used `await MagicMock()` (not awaitable) and `mock.transaction.call_args[0][0]` (broken after override). Rewrote both unit-test files with `FakeDB`/`FakeCache` fakes (real async context managers + recorded `execute` SQL/params).

### Completion Notes List

**Implementation complete; test execution PENDING.**

All seven tasks are implemented and the unit + integration tests are authored and reviewed by inspection. `ruff` + `pyrefly` (`uv tox -e lint`) pass. **However the pytest suite has NOT been executed in this environment**: the tox test venv build (psycopg[binary,pool], aiokafka, opentelemetry, fastapi, testcontainers) triggers repeated OOM crashes on this WSL2 host, and the user directed that tests not be run now. Task checkboxes are intentionally left **unchecked** and Status stays **in-progress** (not `review`) until `uv tox -e test` (units) and `uv tox -e test -- --run-slow` (integration) are run and green. Run those, then flip the boxes + Status to `review`.

**Design decisions (ambiguity resolutions):**

- **Rating mode = honour-incoming (confirmed with user).** The `CdrEvent` model makes `cost_paise` mandatory, so the CDR's `cost_paise` is authoritative (the simulator/producer pre-rates). `consumer/rating.py` provides the canonical plan-based rater `rate_cdr(cdr, PlanTariff)` (voice per-second, unlimited→0, SMS/data flat) as the **reference** contract the simulator (Story 2.8) must use to produce `cost_paise` — it is NOT invoked on the P95 hot path. This satisfies AC #7 (per-second + unlimited→0 rule is implemented) and Task 2 (honour incoming + documented).
- **Rate source:** per-unit rates are explicit fields on `PlanTariff` (no plan-price derivation), since the user stated "there is no charge from here; CDR does the rating, simply reuse it". SMS/data use a simple flat per-unit default (complex tariffs deferred, per Dev Notes).
- **`balance:{msisdn}` resolution:** CDRs carry `subscriber_id` but not `msisdn`. Warm-up builds an in-process `subscriber_id→msisdn` index (and the reverse `msisdn→subscriber_id` for flusher upserts) from `billing_wallet_balances`, so the hot path resolves msisdn with an O(1) dict lookup — no DB I/O on the P95 path. A CDR whose `subscriber_id` is missing from the index is logged (subscriber_id only, PII-safe) and skipped (CDR still forwards to enriched); documented as a degradation, not a crash.
- **No new migration** (Schema Reconciliation honoured). Flush target = `billing_wallet_balances` (`ON CONFLICT (msisdn) DO UPDATE`); per-deduction forensic ledger = `billing_transactions` (`transaction_type='cdr_deduction'`, `amount_paise=-cost`, `reference_type='cdr'`, `reference_id=cdr_id`, before/after balances). The immutable `billing_audit_log` row + cross-pipeline `trace_id` are Story 2.4.
- **Idempotency:** relies entirely on Story 2.2's `dedup:{cdr_id}` guard — `BatchProcessor` invokes `engine.deduct` only on first-sight events. No second dedup mechanism added (Dev Notes).
- **P95 / observability:** `deduct` emits an OTEL span `balance.deduction` (cost, cdr_type, balance_after, masked msisdn[-4:]) as a child of the upstream CDR trace (attached by the batch processor). P95 timing is asserted structurally (span emitted), not as a CI perf benchmark.
- **Testing convention note:** the repo moved to conftest-hook skip-by-default (`--run-slow`/`--run-integration`); the integration test is marked `slow`+`integration` so it skips under plain `pytest` (no container spin-up, low RAM). `psycopg[binary,pool]` (both extras) is required so importing `adapters.postgres` at collection succeeds.

### File List

**New files:**
- `cdr-pipeline/src/core/protocols/db.py` — `DatabaseProtocol` (`ping`, `transaction`, `close`).
- `cdr-pipeline/src/adapters/postgres.py` — `Psycopg3AsyncAdapter` + `conninfo_from` (mirrors `service_webapp`).
- `cdr-pipeline/src/consumer/rating.py` — `PlanTariff`, `rate_cdr` (reference plan-based rater).
- `cdr-pipeline/src/consumer/startup.py` — `load_balances_from_postgres` + `BalanceWarmupState`.
- `cdr-pipeline/src/consumer/balance_writer.py` — `BalanceEngine` (hot-path `deduct` + async flusher) + `LedgerRow`.
- `cdr-pipeline/tests/unit/test_rating.py`
- `cdr-pipeline/tests/unit/test_startup.py`
- `cdr-pipeline/tests/unit/test_balance_writer.py`
- `cdr-pipeline/tests/integration/test_balance_engine.py` (slow + integration; Postgres + Valkey testcontainers).

**Modified files:**
- `cdr-pipeline/src/core/protocols/cache.py` — added `incr_by`, `set_many`.
- `cdr-pipeline/src/adapters/redis.py` — implemented `incr_by` (INCRBY) + pipelined `set_many` (warm-up bulk SET, no TTL, 5K chunks).
- `cdr-pipeline/src/core/config.py` — `BalanceFlushSettings` (`interval_seconds=2.0`, `dirty_threshold=5000`) + `settings.balance_flush`.
- `cdr-pipeline/src/main.py` — Postgres adapter, `engine.warmup()` before consumer loop, `balance_hook=engine.deduct`, flusher `run()`/`stop()`, graceful shutdown order.
- `cdr-pipeline/pyproject.toml` — `psycopg[binary,pool]>=3.2` runtime + both tox env `deps`.

## Change Log

| Date | Change |
| --- | --- |
| 2026-06-23 | Story 2.3 implementation: balance writer hot path (INCRBY), plan-based rating reference, startup warm-up, async 2s/5K Postgres flusher + `billing_transactions` ledger, OTEL span, main.py wiring, unit + integration tests. Lint green; **test execution pending (OOM constraint, user-directed)**. |

## Review Findings

Review run 2026-06-23 (bmad-code-review, 3 parallel layers: Blind Hunter / Edge Case Hunter / Acceptance Auditor). Scope: branch diff vs `main` scoped to the Story 2.3 File List (14 files, +2,162). Outcome: **1 decision-needed, 15 patch, 6 defer, 16 dismissed (false positives refuted by schema/model).** Headline: a CRITICAL runtime bug (`$N` placeholders vs psycopg3 `%s`) that the unrun integration test would have caught — reinforces the spec's own gate: do not flip to `review`/`done` until `uv tox -e test -- --run-slow` is green.

### Decision-needed

_Resolved 2026-06-23 (shyam): overdraft policy = **allow + signal** — hot path stays O(1) (no compensating write / race); when `balance_after < 0`, set span attr `balance.overdraft=true` and increment an overdraft counter; leave balance negative and reconcile out-of-band. Converted to a patch below._

### Patch

- [ ] [Review][Patch] **Overdraft policy (resolved: allow + signal).** Keep `INCRBY -cost` O(1) — no compensating write/race. When `balance_after < 0`, set span attr `balance.overdraft=true` and bump an overdraft counter metric; do not refund/clamp. Record the policy in Dev Notes. [balance_writer.py:190-193] *(resolved from decision-needed)*
- [ ] [Review][Patch] **[CRITICAL] SQL uses `$1..$6` placeholders; psycopg3's default cursor requires `%s`.** Both `_BALLED_UPSERT_SQL` and `_LEDGER_INSERT_SQL` fail at runtime (every flush raises) → AC#3 flush and AC#6 ledger are entirely non-functional. The integration test repeats the `$N` style so it would fail too; unit tests pass only because `FakeConn.execute` doesn't parse placeholders. Confirmed: `service_webapp` uses `%s` exclusively; no `ClientCursor` override exists in cdr-pipeline. Fix: rewrite both statements to `%s` and the test's seed/assert SQL likewise, then run the integration test. [balance_writer.py:41-78; test_balance_engine.py] *(found by Acceptance Auditor + lead; missed by both hunters)*
- [ ] [Review][Patch] **[HIGH] Flush clears `_dirty_msisdns`/`_ledger_queue` BEFORE the transaction commits → permanent loss on flush failure.** On any DB error (incl. the `$1` bug or an outage) the dirty msisdns and ledger rows are dropped with no retry; the loop catches the exception, backs off 1s, and the next tick sees an empty set. Under sustained DB failure this is **continuous silent money/ledger loss every ~2s**. Fix: snapshot, attempt the commit, and only clear on success (leave rows in place for the next flush on failure). [balance_writer.py:231-235, 295-297] *(blind+edge)*
- [ ] [Review][Patch] **[HIGH] Flush does N sequential `conn.execute` round-trips** (one per dirty msisdn + one per ledger row). At the 5000-key threshold that is up to ~10K sequential awaits inside one transaction — blocks the event loop and blows the 2s flush interval. Fix: `executemany()` for the upsert batch and the ledger batch (or a single bulk `VALUES`/`unnest` upsert). [balance_writer.py:249-267] *(edge)*
- [ ] [Review][Patch] **Consumer/management task crashes hang shutdown and skip the final flush.** `consumer_task`/`mgmt_task` are created without observation; if `processor.run()` raises, the exception is unretrieved and `await stop_event.wait()` blocks forever (only SIGKILL recovers, losing the final flush). Fix: `asyncio.gather(..., return_exceptions=True)` or a `done_callback` that sets `stop_event`. [main.py:146-151] *(edge)*
- [ ] [Review][Patch] **Empty warm-up → silent total billing outage.** If `billing_wallet_balances` is empty (fresh/misconfigured DB), warm-up returns `count=0`, the index is empty, and **every** `deduct` silently skips (warning per CDR) with no hard error. Fix: fail-fast (raise) or CRITICAL log + metric when `count==0`. [balance_writer.py:139-149; main.py:104-106] *(edge)*
- [ ] [Review][Patch] **`set_many` can partially seed Valkey.** A dropped connection mid-pipeline leaves some `balance:{msisdn}` keys unset; those subscribers then `INCRBY` from 0 → silently wrong/negative balances. Fix: check each pipeline's results, retry/accumulate failed chunks, and surface a failure count. [redis.py:74-89] *(edge)*
- [ ] [Review][Patch] **Unbounded `_dirty_msisdns`/`_ledger_queue` under sustained flush failure.** If the flusher keeps failing, both grow without limit → OOM; no backpressure to the consumer. Fix: cap sizes and signal backpressure (pause batching) when exceeded. [balance_writer.py:197-209] *(edge)*
- [ ] [Review][Patch] **Shutdown `finally` block not wrapped per-close.** If `consumer.stop()` raises, `engine.stop()` (final flush) and the remaining `producer/db/cache` closes are skipped. Fix: wrap each close in its own `try/except`. [main.py:152-161] *(edge)*
- [ ] [Review][Patch] **`stop()`'s final `_flush` can overlap the flusher loop without a lock** (especially on the 5s-timeout cancel path). Fix: serialize `_flush` with an `asyncio.Lock`. [balance_writer.py:312-339] *(edge)*
- [ ] [Review][Patch] **`stop()` final-flush failure is swallowed** (only logged). Fix: propagate or emit an operator-visible signal (metric/alarm) so shutdown-time data loss is not silent. [balance_writer.py:334-337] *(blind+edge)*
- [ ] [Review][Patch] **Dirty msisdn with no `subscriber_id` in the reverse index is dropped after the set is cleared** → that wallet is never flushed until restart (silent Valkey/Postgres drift). Fix: re-add to the dirty set on the miss so it's retried. [balance_writer.py:250-253] *(blind+edge)*
- [ ] [Review][Patch] **`test_flusher_triggers_on_dirty_threshold` adds the dirty key before the loop starts**, so the threshold is met at t=0 and the 0.3s sleep proves nothing. Fix: add the dirty key while the loop is running. [test_balance_writer.py] *(blind)*
- [ ] [Review][Patch] **`rate_cdr` falls through to the data branch for any non-voice/non-sms `cdr_type`** (no explicit `else: raise`). Currently defended by the model's discriminated union, but add a guard for defense-in-depth. [rating.py:59-71] *(edge)*
- [ ] [Review][Patch] **`_BALLED_UPSERT_SQL` typo** → `_BALANCE_UPSERT_SQL` (module-private, lint-clean only). [balance_writer.py:41] *(blind)*
- [ ] [Review][Patch] **`_flusher_running` is set inside the loop, not in `run()`.** An immediate `stop()` after `run()` can let one cycle run (covered by the 5s timeout, but fragile). Fix: set `_flusher_running = True` in `run()` before `create_task`. [balance_writer.py:299-310] *(blind+edge)*

### Defer (pre-existing / out-of-scope; logged to deferred-work.md)

- [x] [Review][Defer] **AC#1 names topic `cdr.enriched.filtered` but the code (correctly) consumes `cdr.raw`** via the Story 2.2 `BatchProcessor` seam the spec directs. Code is right; AC text should be corrected. [main.py:88-91]
- [x] [Review][Defer] **`incr` on `CacheProtocol` has no caller** (the 2.2 dedup metric isn't wired in this diff). [redis.py:66-68]
- [x] [Review][Defer] **OTEL spans emitted but no exporter dependency** — spans go to a no-op processor; P95 unverifiable in prod (Story 1.5 infra). [pyproject.toml]
- [x] [Review][Defer] **Flusher inner loop busy-polls at 10 Hz** (`asyncio.sleep(0.1)`); works, minor CPU. An `asyncio.Event` signalled by `deduct` would be cleaner. [balance_writer.py:287-291]
- [x] [Review][Defer] **Unlimited-bundle `cost=0` still performs an `INCRBY 0` round-trip** on the hot path for every free CDR (consistency over micro-opt). [balance_writer.py:190]
- [x] [Review][Defer] **`_management_lifespan` has a dead `finally: pass`** and never closes `JWTValidator` (Story 2.5 scope). [main.py:56-64]

### Dismissed (16) — refuted by schema / model contract

Negative-`cost_paise` credit (model `Field(ge=0)`); warm-up duplicate overwrite (schema UNIQUE on `subscriber_id`+`msisdn`); `balance_paise` NULL → `'None'` seed (`BIGINT NOT NULL DEFAULT 0`); `description=cdr_type` "wrong" (spec Task 5 explicitly says *e.g. cdr_type*); ledger double-insert / `deduct` called twice (`balance_hook` fires only after the 2.2 dedup guard, first-sight); `processor.stop()` "async from signal" (it is `def`, sync); unknown-`cdr_type` returns `None` (discriminated union restricts to voice/sms/data); `gen_random_uuid()` needs pgcrypto (baseline requirement, 30+ V1 tables use it); rating overflow / `round()` type (int fields, bounded 30-day duration); UUIDv4-vs-v7 asymmetry (matches schema `DEFAULT`s); paise int64 overflow (theoretical 9.2e18); `int(val_str)` ValueError (warm-up writes `str(int)`, `INCRBY` keeps ints); 300K-row warm-up OOM (acceptable per AC#5); `subscriber_id` UUID-case mismatch (both use `str(UUID)` lowercase canonical); reverse-index mutated mid-flight (immutable post-warm-up); duplicate signal-handler registration (theoretical).
