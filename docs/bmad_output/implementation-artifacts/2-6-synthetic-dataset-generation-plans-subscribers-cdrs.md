# Story 2.6: Synthetic Dataset Generation — Plans, Subscribers & CDRs

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want a script that generates a realistic synthetic dataset (1K plans, 300K subscribers, 5M CDRs) following the correct creation order,
so that all downstream epics have representative data for testing agents, forecasts, and billing flows.

## Acceptance Criteria

1. **Given** Flyway migrations have run, **Then** a versioned seed migration has populated **1,000 plans** in `plans_plans` (UUIDv4 PKs via `gen_random_uuid()`) with realistic Indian-telecom plan names, `validity_days ∈ {28, 56, 84}`, `data_limit_mb`, `voice_minutes`, `sms_count` quotas (NULL = unlimited), and `price_paise` (integer paise). (ARCH-24)
2. **When** `just seed` is executed, **Then** `scripts/generate_synthetic_data.py` inserts **300,000 subscribers** into `identity_subscribers` via the **psycopg3 COPY protocol** in batches of **50,000**; every subscriber references a valid `plan_id` from `plans_plans`. (ARCH-24)
3. **And** the same script generates **5,000,000 CDR** rows in `billing_cdr_events` (PK is UUIDv7 via the DB default `uuid_generate_v7()`) referencing valid subscriber `subscriber_id`s; `start_time`/`end_time` span **90 days**; `cdr_type` distribution ≈ **voice 60% / data 30% / SMS 10%**; type-specific columns populated per `cdr_type` (voice/sms/data variants), `cost_paise` set, `roaming`/`telecom_circle`/`cell_tower_id` realistic.
4. **And** approximately **0.5%** of subscribers carry embedded fraud signals: unusual CDR velocity (**> 200 events/day**) and/or a SIM-swap signal; affected CDRs have `fraud_flag = TRUE`. (ARCH-25)
5. **And** the SOP knowledge base is seeded via `scripts/sop_generator.py`, writing rows to `sop_rules` and `sop_knowledge_chunks`. (ARCH-26)
6. **And** `just seed` is **idempotent** — re-running truncates and re-seeds without error (no duplicate-key failures, no orphaned FKs).
7. **And** seed completion logs the counts: plans, subscribers, CDRs, and fraud-flagged subscribers.

## Tasks / Subtasks

- [ ] **Task 1: Plans seed migration (1,000 plans)** (AC: #1)
  - [ ] Add a Flyway **versioned** migration that `INSERT`s 1,000 rows into the **existing** `plans_plans` table (schema is already in `V1__baseline_schema.sql:107-122` — do NOT redefine the table). Generate realistic Indian prepaid plan combinations across `validity_days ∈ {28,56,84}`, mixed data/voice/SMS bundles (`NULL` for unlimited), unique `plan_name` + `plan_code`, `price_paise` as integer paise. [Source: epics.md#Story-2.6 (line 1006); V1__baseline_schema.sql:107-122]
  - [ ] **🚨 Version-number conflict — resolve before writing:** Story 2.3 already reserves `V5__billing_schema.sql` for billing-table DDL, and on-disk migrations are `V1`,`V2`,`V3`. The epic text calls this "V5" but that number is taken. **Pick the next free sequential version** after the highest committed migration (coordinate with Story 2.3's number), e.g. `V6__seed_plans.sql`. Confirm by listing `service_webapp/db/migrations/` at implementation time. Flyway runs versions in order, so the seed must sort **after** any migration that (re)defines `plans_plans`. [Source: 2-3 story (V5__billing_schema.sql); architecture.md#1.12.2 (line 1229, "V5__seed_plans.sql")]
  - [ ] Idempotency at the migration layer: Flyway versioned migrations run once. Make the INSERTs safe under the script's truncate/reseed cycle by using `ON CONFLICT (plan_code) DO NOTHING` so a manual re-apply is harmless. Plans are reference data and must **not** be truncated by the synthetic-data script (subscribers FK to them).
- [ ] **Task 2: `generate_synthetic_data.py` — subscribers via COPY** (AC: #2, #6)
  - [ ] Create `scripts/generate_synthetic_data.py`. Load config via `from core.config import settings` (run with `cd service_webapp && PYTHONPATH=src python ../scripts/...` — match the existing `just` invocation pattern; confirm import path works or place the script under `service_webapp/scripts/`). Build the Postgres conninfo from `settings.db.*`. [Source: service_webapp/src/core/config.py:40-100; justfile#seed]
  - [ ] Insert 300,000 rows into `identity_subscribers` using **psycopg3 `cursor.copy()`** (COPY protocol) in batches of **50,000**. Required columns: `id` (UUIDv4), `msisdn` (unique, Indian format e.g. `91XXXXXXXXXX`), `subscriber_name`, `status='active'`, `plan_id` (random valid plan), timestamps. Use `faker` for names if added to deps. [Source: epics.md#Story-2.6 (line 1008); V1__baseline_schema.sql:37-50; architecture.md#1.12.2 (lines 1230-1236)]
  - [ ] **Idempotency (AC #6):** at the start, `TRUNCATE billing_cdr_events, identity_subscribers RESTART IDENTITY CASCADE` (NOT `plans_plans`). Order matters: truncate CDRs (child) then subscribers. Wrap the whole run so a re-run reaches the same end state. [Source: epics.md#Story-2.6 (line 1016)]
  - [ ] Also seed `billing_wallet_balances` (one row per subscriber, `balance_paise` = the plan's initial credit) so the balance engine (Story 2.3) and self-care portal (Epic 3) have warm data. This is implied by the pipeline contract even though not in the AC list — note it in Completion Notes if descoped. [Source: V1__baseline_schema.sql:161-173 (billing_wallet_balances); 2-3 story (load_balances_from_postgres warm-up)]
- [ ] **Task 3: 5M CDR generation** (AC: #3, #4)
  - [ ] In the same script, generate 5,000,000 `billing_cdr_events` rows via COPY (batched, target < 5 min). Let the DB default assign the UUIDv7 PK (`id` omitted from the COPY column list, or supply `uuid7`-generated values — **never `uuid4`** for CDR PKs). [Source: architecture.md#1.7.1 (UUIDv7 strategy); V1__baseline_schema.sql:175-209; 2-1 story (UUIDv7)]
  - [ ] Distribute `cdr_type` ≈ voice 60% / data 30% / SMS 10%. Populate the **type-specific** columns: voice → `from_number,to_number,call_direction,duration_seconds,call_status`; sms → `message_direction,sms_status`; data → `network_type,downloaded_mb,uploaded_mb,volume_mb,apn,imei,operator_id`. Leave the other variants' columns NULL. Set `cost_paise`, `start_time`/`end_time` spread across **90 days**, `telecom_circle`, `cell_tower_id`, `roaming`. Enum values must match the DB enums (`cdr_type_enum`, `call_direction_enum`='MO'/'MT', `call_status_enum`, `sms_status_enum`, `network_type_enum`='2G'..'5G'). [Source: V1__baseline_schema.sql:14-31 (enums), 175-209 (columns)]
  - [ ] **Fraud signal injection (AC #4):** pick ≈0.5% of subscribers; for each, either emit CDR velocity > 200 events/day (concentrated bursts) and/or mark a SIM-swap signal, and set `fraud_flag = TRUE` on their anomalous CDRs. This feeds Epic 6 fraud-agent testing. [Source: epics.md#Story-2.6 (line 1012); architecture.md#1.6.2 (fraud metrics: CDR velocity, SIM-swap count)]
- [ ] **Task 4: `sop_generator.py` — SOP knowledge base** (AC: #5)
  - [ ] Create `scripts/sop_generator.py` that writes to `sop_rules` (`rule_name,domain,trigger_condition,response_template,priority,is_active`) and `sop_knowledge_chunks` (`source_document,chunk_text,vector_embedding_id,chunk_index,domain`). Both UUIDv4 PKs. Idempotent (truncate + reseed, or `ON CONFLICT`). These chunks are the source for Story 2.7's `sop_chunks` Milvus collection — keep `chunk_text`/`domain` meaningful. [Source: epics.md#Story-2.6 (line 1014); V1__baseline_schema.sql:554-583; 2-7 story (sop_chunks seeded from this table)]
- [ ] **Task 5: Wire `just seed` + completion logging** (AC: #6, #7)
  - [ ] Replace the **stub** `seed` recipe in the root `justfile` (currently `@exit 1`) so it runs `generate_synthetic_data.py` then `sop_generator.py`. Match the existing recipe conventions (`cd service_webapp && PYTHONPATH=src ...` or `cd ... && python scripts/...`). [Source: justfile#seed (stub lines ~67-71); 1-3 story (justfile recipes)]
  - [ ] On completion, log structured counts: `plans`, `subscribers`, `cdrs`, `fraud_flagged_subscribers` (AC #7). Use the project logging pattern. Do **not** print PII.
- [ ] **Task 6: Tests** (AC: #2, #3, #4, #6)
  - [ ] Integration (`@pytest.mark.slow`, testcontainers Postgres, rootless podman `DOCKER_HOST=unix:///run/user/1000/podman/podman.sock`): run the generators at **reduced scale** (env-overridable counts, e.g. 50 plans / 500 subscribers / 5K CDRs) and assert: row counts, FK validity (every subscriber `plan_id` exists, every CDR `subscriber_id` exists), `cdr_type` distribution within tolerance, ~0.5% fraud-flagged, and that a **second run** yields identical counts (idempotency). [Source: 1-4 story (testcontainers); 2-1 story (slow integration pattern)]
  - [ ] Unit: helpers (MSISDN formatting, plan-attribute generation, type-specific CDR field builders, distribution sampler) are pure and tested without a DB. Add any new import (`faker`, etc.) to the relevant tox env `deps`.

## Dev Notes

### Scope boundary

- **DOES:** the plans seed migration (1K plans into existing `plans_plans`), `generate_synthetic_data.py` (300K subscribers + 5M CDRs via COPY, 90-day span, type distribution, ~0.5% fraud signals, idempotent truncate/reseed, wallet balances), `sop_generator.py` (SOP rules + knowledge chunks), `just seed` wiring + count logging, tests at reduced scale.
- **DOES NOT:** seed **Milvus** vectors (that is Story 2.7 / `just seed-milvus`), build the CDR consumer or balance engine (2.2/2.3), or define any table DDL beyond the plans **seed** (all tables already exist in `V1`). Do not create `seed_milvus.sh` here — it belongs to 2.7.

### 🚨 Tables already exist in V1 — this story SEEDS, it does not define schema

- `V1__baseline_schema.sql` already creates `plans_plans`, `identity_subscribers`, `billing_cdr_events`, `billing_wallet_balances`, `sop_rules`, `sop_knowledge_chunks` with full columns, enums, indexes, and FKs. **Do not recreate them.** This story only adds INSERT data (a versioned plans-seed migration + the Python generators). [Source: V1__baseline_schema.sql:37-50,107-122,161-209,554-583]
- Postgres extensions (`pg_uuidv7`, `pgcrypto`, `pg_trgm`, `btree_gin`) are installed at container init in `docker/postgres/init/01_extensions.sql`. `billing_cdr_events.id` defaults to `uuid_generate_v7()` — let the DB assign it or use the `uuid7` package; **never `uuid4`** for CDR PKs. [Source: 2-1 story (UUIDv7); docker/postgres/init/01_extensions.sql]

### Script location — follow the epic AC + justfile, not the architecture path

- **Variance:** architecture §1.12.2 names `service_webapp/db/seed/synthetic_generator.py`, but the **epic ACs** and the **existing `justfile` stubs** both reference `scripts/generate_synthetic_data.py` and `scripts/sop_generator.py`. Follow the epic/justfile convention (`scripts/…`). Pick whichever the `import core.config` path supports cleanly — if a bare `scripts/` script can't import `service_webapp/src/core/config`, either run it with `PYTHONPATH=service_webapp/src` or place the file under `service_webapp/scripts/`. Document the final location + invocation in Completion Notes. [Source: epics.md#Story-2.6 (lines 1008,1014); justfile (seed stub); architecture.md#1.12.2]

### COPY protocol & performance (the 5M-row constraint)

- Use psycopg3 `cursor.copy()` with batched writes (50K subscribers/batch per AC #2; large CDR batches). COPY is the only realistic way to hit the < 5-min generation target for 5M rows. Avoid per-row `INSERT`. Generate data in memory per batch, stream via COPY, commit per batch. [Source: architecture.md#1.12.2 (lines 1230,1236 — psycopg3 COPY, batches of 50K, <5 min)]
- Money is **integer paise** everywhere (`price_paise`, `cost_paise`, `balance_paise`) — never floats. [Source: architecture.md#1.12.2 (line 1233)]

### Idempotency rules (AC #6)

- `just seed` must be safe to re-run. Truncate the **generated** tables only — `TRUNCATE billing_cdr_events, identity_subscribers, billing_wallet_balances RESTART IDENTITY CASCADE` (child → parent order) — then regenerate. Do **not** truncate `plans_plans` (reference data, FK target) or SOP tables on the subscriber/CDR path; SOP generator manages its own truncate/`ON CONFLICT`. [Source: epics.md#Story-2.6 (line 1016)]

### Config singleton — reuse, don't reinvent

- `from core.config import settings` gives `settings.db.{host,port,name,user,password}`, eager-loaded and fail-fast. Build the conninfo from these; do not introduce a second settings object or hardcode credentials. `password` is a `SecretStr` — use `.get_secret_value()`. [Source: service_webapp/src/core/config.py:40-100; 2-1 story (reuse settings)]

### Testing standards summary

- `uv tox` `lint` (ruff + ruff format --check + pyrefly) and `test` (pytest `-m "not slow"`). Unit tests for pure helpers need no DB; the full generators run only under a `slow` testcontainers Postgres integration test at **reduced, env-overridable scale** (do not generate 5M rows in CI). ruff line-length 120, py311. Add new runtime imports to the tox env `deps`. [Source: 1-4 story (testcontainers, rootless podman); 2-1 story (slow integration); service_webapp/pyproject.toml]

### Project Structure Notes

- **NEW:** `scripts/generate_synthetic_data.py`, `scripts/sop_generator.py` (or under `service_webapp/scripts/` — see location note), a versioned plans-seed migration `service_webapp/db/migrations/V<next>__seed_plans.sql`, tests under `service_webapp/tests/`.
- **MODIFIES:** root `justfile` (`seed` recipe: stub → real), `service_webapp/pyproject.toml` (`faker`/any new dep + tox env deps).
- **Variances flagged:** (1) migration version number — epic says V5 but it's taken by Story 2.3; use the next free number. (2) script path — `scripts/` (epic/justfile) vs `db/seed/` (architecture); follow `scripts/`.

### References

- [Source: epics.md#Story-2.6 (lines 992-1018)]
- [Source: architecture.md#1.12.2 (synthetic data generation, FR-71 — scale, order, COPY, fraud signals, paise; lines 1196-1236)]
- [Source: architecture.md#1.7.1 (UUID strategy: UUIDv7 for CDRs, UUIDv4 for reference tables), #1.6.2 (fraud metrics)]
- [Source: service_webapp/db/migrations/V1__baseline_schema.sql:14-31 (enums), 37-50 (subscribers), 107-122 (plans), 161-209 (wallet + CDRs), 554-583 (SOP tables)]
- [Source: service_webapp/src/core/config.py:40-100 (settings singleton, DatabaseSettings)]
- [Source: justfile (seed / seed-milvus stubs); docker/postgres/init/01_extensions.sql (pg_uuidv7)]
- [Source: 2-1 story (UUIDv7, envelope, slow integration), 2-3 story (V5 billing schema, wallet warm-up), 2-7 story (consumes sop_knowledge_chunks), 1-4 story (testcontainers + rootless podman)]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
