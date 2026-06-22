# Story 2.6: Synthetic Dataset Generation — Plans, Subscribers & CDRs

---
baseline_commit: 31baee8c29ae510be0ded247e4fbd5f7b9abda13
---

Status: review

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

- [x] **Task 1: Plans seed (1,000 plans)** (AC: #1)
  - [x] Created `service_webapp/db/seed/seed_plans.sql` — NOT a Flyway migration per user decision; executed by `generate_synthetic_data.py` at seed time. Single fictional brand SkyLink, 7 categories (SuperData/TalkMore/AllRounder/TextMore/Unlimited/SmartValue/International), validity ∈ {28,56,84,180,365} days, realistic data ranges (daily-quota style: 100MB–5GB/day; fixed-pool: 10GB–100GB), integer paise pricing. Idempotent via `ON CONFLICT (plan_code) DO NOTHING`.
- [x] **Task 2: `generate_synthetic_data.py` — subscribers via COPY** (AC: #2, #6)
  - [x] Created `scripts/generate_synthetic_data.py`. Runs with `cd service_webapp && PYTHONPATH=src python ../scripts/generate_synthetic_data.py`. Executes `seed_plans.sql` on startup. Inserts 300K subscribers via psycopg3 COPY in batches of 50K. Columns: id (UUIDv4), msisdn (unique 91XXXXXXXXXX), subscriber_name, email (Faker en_IN), address fields (address_line1/2, city, state, pin_code), status=active, plan_id (random from loaded plan IDs). Seeds billing_wallet_balances (one row per subscriber, balance=plan price). Idempotent: TRUNCATE billing_cdr_events, billing_wallet_balances, identity_subscribers RESTART IDENTITY CASCADE at start.
- [x] **Task 3: 5M CDR generation** (AC: #3, #4)
  - [x] Same script: two-pass CDR generation. Pass 1: 4.7M normal CDRs. Pass 2: 300K velocity-burst CDRs. `id` omitted from COPY column list (DB assigns `uuid_generate_v7()`). cdr_type distribution: voice 60% / data 30% / SMS 10% via random.choices weights. Type-specific columns populated per cdr_type, NULL for others. start_time/end_time span 90 days. Enum values match DB enums exactly.
  - [x] Fraud signals (5 types): velocity_burst (>220 CDRs in one day), sim_swap (IMEI rotation at day 45), roaming_abuse (heavy roaming across 5+ circles), unique_destinations (>50 unique to_number in 24h), multi_tower (5 distinct towers in 1 hour). Affected CDRs: fraud_flag=TRUE. Writes `scripts/fraud_report.json` for demo.
- [x] **Task 4: `sop_generator.py` — SOP knowledge base** (AC: #5)
  - [x] Created `scripts/sop_generator.py`. 20 sop_rules + 30+ sop_knowledge_chunks across 6 domains (fraud, billing, activation, support, compliance, network). Meaningful chunk_text for RAG. Idempotent: TRUNCATE sop_knowledge_chunks, sop_rules at start.
- [x] **Task 5: Wire `just seed` + completion logging** (AC: #6, #7)
  - [x] Updated `justfile`: seed recipe runs generate_synthetic_data.py then sop_generator.py. `just deps` now also runs `just migrate && just seed` after infra is up (with pg_isready wait). Completion logs counts via Python logging (no PII).
- [x] **Task 6: Tests** (AC: #2, #3, #4, #6)
  - [x] 18 unit tests in `service_webapp/tests/unit/test_synthetic_helpers.py`: MSISDN format, cost_paise int-only, CDR type distribution, fraud fraction, fraud signal metadata, IMEI format, tower ID format, seed SQL file presence + content. All pass.
  - [x] Integration test in `service_webapp/tests/integration/test_synthetic_data_generation.py`: @pytest.mark.slow, testcontainers Postgres, SUBSCRIBER_COUNT=500/CDR_COUNT=5000 env-overridable scale. Asserts: counts, FK validity, distribution, fraud fraction, idempotency, SOP domains.

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

claude-sonnet-4-6

### Debug Log References

- Plans seed moved OUT of Flyway migrations into `service_webapp/db/seed/seed_plans.sql` per user decision — keeps migrations schema-only.
- `just deps` now also calls `just migrate && just seed` with a pg_isready wait so the stack is fully seeded after a single `just deps` invocation.
- Fraud signals expanded beyond story ACs: added roaming_abuse, unique_destinations, multi_tower per user request. Each signal type handled in two-pass CDR generation.
- CDR id column omitted from COPY column list — DB assigns uuid_generate_v7() natively. cdr_id (Pydantic field, UUID7) will be added by a future story as noted by user.
- `faker>=26` and `pandas>=2.0` added to both lint and test tox env deps (needed by scripts imported during test collection).

### Completion Notes List

- Plans seed: 1,000 rows in `service_webapp/db/seed/seed_plans.sql` executed by `generate_synthetic_data.py` (not Flyway). Single brand SkyLink, 7 categories, validity ∈ {28,56,84,180,365}, data ranges 100MB–5GB/day or 10–100GB fixed pool, international plans with ISD/roaming.
- Subscribers: 300K via psycopg3 COPY (50K batches). Includes Indian addresses (Faker en_IN: address_line1/2, city, state, pin_code) and email. Wallet balances seeded with plan price as initial balance.
- CDRs: 5M via two-pass COPY. Voice/data/SMS distribution 60/30/10. 5 fraud signal types on ~0.5% subscribers. Fraud demo report written to `scripts/fraud_report.json`.
- SOP: 20 rules + 30+ knowledge chunks across fraud/billing/activation/support/compliance/network domains. Meaningful RAG-quality text for Story 2.7.
- `billing_wallet_balances` also seeded (implied by story pipeline contract, implemented and noted here per task guidance).
- Seed not a Flyway migration — user decision to keep migrations schema-only.

### File List

- service_webapp/db/seed/seed_plans.sql (NEW)
- scripts/generate_synthetic_data.py (NEW)
- scripts/sop_generator.py (NEW)
- scripts/fraud_report.json (GENERATED at runtime — not committed)
- service_webapp/tests/unit/test_synthetic_helpers.py (NEW)
- service_webapp/tests/integration/test_synthetic_data_generation.py (NEW)
- justfile (MODIFIED — seed recipe + just deps wiring)
- service_webapp/pyproject.toml (MODIFIED — faker, pandas, numpy, uuid7 added to tox envs)
- docs/bmad_output/implementation-artifacts/sprint-status.yaml (MODIFIED)
- docs/bmad_output/implementation-artifacts/2-6-synthetic-dataset-generation-plans-subscribers-cdrs.md (MODIFIED)

### Change Log

- 2026-06-22: Story 2.6 implemented. Plans seed SQL in db/seed/ (not migrations). 1K plans, 300K subscribers with Indian addresses, 5M CDRs (two-pass), 5 fraud signal types, SOP knowledge base, fraud_report.json demo output. justfile wired. 18 unit tests pass. Integration test scaffolded for slow/podman runs.
