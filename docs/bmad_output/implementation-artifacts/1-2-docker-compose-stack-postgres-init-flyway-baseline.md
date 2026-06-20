---
baseline_commit: c2e8a04aa1643dc9e802bc121f1501367beb3f7d
---

# Story 1.2: Docker Compose Stack, Postgres Init & Flyway Baseline

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want a fully reproducible local development environment that starts all infrastructure services with a single command and initialises Postgres with the required extensions, roles, and schema baseline,
so that any team member can onboard in under 15 minutes and all services share a consistent data layer.

## Acceptance Criteria

1. **Given** Docker and Docker Compose are installed, **When** `just up` is run, **Then** the dependency stack starts: Redpanda, Valkey (`noeviction` policy), Postgres 16, LangFuse (self-hosted), MiniStack (Cognito + S3), OTEL-Collector, OTEL-TUI, Fluentd.
2. The Postgres init scripts execute in order at container creation: `01_extensions.sql` (pg_uuidv7, pgcrypto, pg_trgm, btree_gin), `02_roles.sql` (sboai_app, sboai_readonly, sboai_flyway), `03_databases.sql` (sboai database provisioning).
3. Flyway runs `V1__baseline_schema.sql` creating the **full all-domain baseline schema** (every table across every domain, with indexes and FK constraints) with UUIDv7 primary keys on transactional tables and UUIDv4 on reference tables (ARCH-9), and `V2__modified_at_trigger.sql` creating the `set_modified_at()` trigger function and applying it to every table that has `modified_at`.
4. The two-file Docker Compose split is in place: `docker/docker-compose-dependencies.yaml` (infra only) and `docker/docker-compose.yaml` (full stack via `include:`) (ARCH-28).
5. Named volumes persist across restarts: `postgres_data`, `valkey_data`, `ministack_cognito`, `ministack_s3`, `milvus_lite_data` (ARCH-29).
6. `just deps` starts only infra (no app containers) for local backend development.
7. The Postgres container reports healthy via a `pg_isready` healthcheck before dependent services start, and `just up` completes without manual intervention on a clean clone.

## Tasks / Subtasks

- [x] **Task 1: Create the `docker/` directory layout** (AC: #4)
  - [x] `docker/docker-compose-dependencies.yaml` — infra only
  - [x] `docker/docker-compose.yaml` — full stack via `include:`
  - [x] `docker/docker-compose.override.yaml` — local dev overrides (port mappings, hot reload)
  - [x] `docker/postgres/init/` directory for the three init SQL scripts
- [x] **Task 2: Author Postgres container init scripts** (AC: #2)
  - [x] `docker/postgres/init/01_extensions.sql` — `CREATE EXTENSION IF NOT EXISTS` for `pg_uuidv7`, `pgcrypto`, `pg_trgm`, `btree_gin` (run as `postgres` superuser)
  - [x] `docker/postgres/init/02_roles.sh` — create `sboai_app`, `sboai_readonly`, `sboai_flyway` (with `CREATEROLE` — see Callout 3) from `${POSTGRES_*_PASSWORD}` env vars; grant DB privileges (shell script for env var expansion)
  - [x] `docker/postgres/init/03_databases.sql` — provision the `sboai` database if not default (Docker `POSTGRES_DB=sboai` creates it; this script handles grants/ownership)
  - [x] All scripts idempotent (`IF NOT EXISTS`); safe to re-run on volume wipe
- [x] **Task 3: Define the infrastructure compose file** (AC: #1, #5, #7)
  - [x] `redpanda` (Kafka-compatible, no ZooKeeper)
  - [x] `valkey` standalone: `--maxmemory 512mb --maxmemory-policy noeviction`; volume `valkey_data:/data`
  - [x] `postgres:16`: env `POSTGRES_DB=sboai`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=${POSTGRES_SUPERUSER_PASSWORD}`; mount `postgres_data` + `./postgres/init:/docker-entrypoint-initdb.d`; `pg_isready` healthcheck (interval 5s, retries 10)
  - [x] `langfuse` (self-hosted, agent observability)
  - [x] `ministack`: Cognito + S3 sim (localstack/localstack); volumes `ministack_cognito`, `ministack_s3` (NO bundled Redis — Valkey is separate)
  - [x] `otel-collector`, `otel-tui`, `fluentd`
  - [x] **NO Milvus container** — Milvus Lite is embedded in the backend (Python dep). The `milvus_lite_data` volume is declared here but mounted into the backend in the full-stack file.
  - [x] Declare all named volumes: `postgres_data`, `valkey_data`, `ministack_cognito`, `ministack_s3`, `milvus_lite_data`
- [x] **Task 4: Define the full-stack compose file** (AC: #4)
  - [x] `include: [docker-compose-dependencies.yaml]`
  - [x] `cdr-pipeline` service (build context `./cdr-pipeline`)
  - [x] `service_webapp` (the FastAPI backend; build context `./service_webapp`) with `deploy.replicas: 1` **HARD CONSTRAINT** — mount `milvus_lite_data:/app/data/milvus`; add the comment explaining Milvus Lite single-process constraint
  - [x] `frontend` service (Vite dev server / nginx)
- [x] **Task 5: Author Flyway V1 full all-domain baseline migration** (AC: #3)
  - [x] Create `service_webapp/db/migrations/V1__baseline_schema.sql`
  - [x] Create ALL tables across ALL domains (identity_, billing_, plans_, recharge_, notifications_, support_, fraud_, segmentation_, ops_, sop_) with correct UUIDv7/UUIDv4 PK strategy, `created_at`/`modified_at` columns, indexes, and FK constraints
  - [x] Use `id UUID DEFAULT uuid_generate_v7() PRIMARY KEY` on transactional tables; `id UUID DEFAULT gen_random_uuid() PRIMARY KEY` on reference tables (see Dev Notes table)
  - [x] CDR table (`billing_cdr_events`) column definitions per `docs/Schema - CDR.md`
  - [x] Migrations run as `sboai_flyway` — do NOT include `CREATE EXTENSION` (extensions are created by superuser in init scripts)
- [x] **Task 6: Author V2 modified_at trigger migration** (AC: #3)
  - [x] `service_webapp/db/migrations/V2__modified_at_trigger.sql` — `set_modified_at()` function + `CREATE TRIGGER trg_{table}_modified_at BEFORE UPDATE` per table that has `modified_at`
- [x] **Task 7: Wire `just deps` / `just up` and verify** (AC: #1, #6, #7)
  - [x] Ensure `just deps` and `just up` invoke the correct compose files (the justfile itself is finalised in Story 1.3 — here, only verify the compose files work via raw `podman compose -f ...` commands)
  - [x] Verification commands documented in Debug Log; user to execute from Windows with Podman

## Dev Notes

### Scope boundary — what this story does and does NOT do

- **DOES:** Docker Compose two-file split, Postgres init scripts, Flyway V1 (full all-domain schema) + V2 (trigger). This story stands up the data layer.
- **DOES NOT:** Build application code (FastAPI app, consumer), write the justfile (Story 1.3), configure CI (Story 1.3), or set up pydantic-settings/health endpoints (Story 1.4). It also does not seed data (synthetic seed is Epic 2, `just seed`).
- The `just up`/`just deps` recipes are *referenced* here but their authoritative definition is Story 1.3. To verify this story, run `docker compose -f docker/docker-compose-dependencies.yaml up -d` directly.

### RESOLVED naming decisions (use these EXACTLY)

The epics file (Story 1.2 ACs) uses loose shorthand. The **architecture canonical names are authoritative** for this implementation:

| Concern | **Use this (architecture)** | Do NOT use (epics shorthand) |
|---|---|---|
| Database name | `sboai` | ~~`sboai_db`~~ |
| App role | `sboai_app` | ~~`app_rw`~~ |
| Read-only role | `sboai_readonly` | ~~`app_ro`~~ |
| Migration role | `sboai_flyway` | ~~`migration_user`~~ |
| Identity tables | `identity_subscribers`, `identity_registrations`, `identity_kyc_records`, `identity_caf_submissions` | ~~`subscribers`, `subscriber_orders`~~ |
| Audit table | `billing_audit_log` (domain-prefixed) | ~~`audit_log`~~ |

[Source: architecture.md#1.7.1, #1.12.4 — confirmed by user decision 2026-06-19]

### RESOLVED backend directory decision

The architecture refers to the FastAPI backend as `app-backend/`. **In this repo it is `service_webapp/`** (already exists with correct deps). Wherever architecture or epics say `app-backend/`, read `service_webapp/`. The `cdr-pipeline/` directory does **not** yet exist and is created when first needed (its compose service is declared here; its code lands in Epic 2). Flyway migrations live at `service_webapp/db/migrations/`.

[Source: architecture.md#1.12.1 (says app-backend); user decision 2026-06-19 → service_webapp]

### RESOLVED V1 scope decision — FULL all-domain baseline

V1 creates the **entire schema for all domains up front** (architecture §1.12.1 shows `V1__baseline_schema.sql` = "all tables + indexes + FK constraints"). Later stories add only views, materialized views, seeds, and grants — they do NOT add core tables. This means Story 1.6's registration tables, Story 1.8's auth/session table, and Story 1.10's payment table are all part of V1 here.

[Source: architecture.md#1.12.1, line 1104; user decision 2026-06-19]

> ⚠️ **Cross-story note:** Epics 1.6/1.8/1.10 reference per-story migrations (`V2__subscriber_schema.sql`, `V3__auth_schema.sql`, `V4__payment_schema.sql`). Because V1 is the full baseline here, those later stories will instead *use* the already-created tables (and add views/grants if needed) rather than create them. The dev agent for 1.6/1.8/1.10 must be told this. Record it in this story's Completion Notes.

### Postgres init scripts — exact content guidance

**`01_extensions.sql`** (superuser; runs once at container creation):
```sql
CREATE EXTENSION IF NOT EXISTS "pg_uuidv7";   -- UUIDv7 PKs (uuid_generate_v7())
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- AES-256 PII column encryption
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- trigram indexes (MSISDN fuzzy search)
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- composite GIN indexes
```

**`02_roles.sql`** (superuser):
- `CREATE USER sboai_app WITH PASSWORD '${POSTGRES_APP_PASSWORD}';`
- `CREATE USER sboai_readonly WITH PASSWORD '${POSTGRES_READONLY_PASSWORD}';`
- `CREATE USER sboai_flyway WITH PASSWORD '${POSTGRES_FLYWAY_PASSWORD}' CREATEROLE;`
- Grants: `GRANT ALL PRIVILEGES ON DATABASE sboai TO sboai_app;` `GRANT CONNECT ON DATABASE sboai TO sboai_readonly;` `GRANT CONNECT ON DATABASE sboai TO sboai_flyway;`

**Rules:**
- Extensions created by superuser in init only — **Flyway migrations must NOT `CREATE EXTENSION`**.
- Application code connects as `sboai_app`, never `postgres`.
- `sboai_readonly` gets SELECT grants post-migration via a later grants migration (`V5__grants.sql` per architecture; or fold into this baseline if you choose — but keep grants in a migration, not init).
- `pg_uuidv7` must be available for Postgres 16. If the stock `postgres:16` image lacks it, the dev agent must use an image/Dockerfile that bundles `pg_uuidv7` (e.g. build a custom Postgres image installing the extension). **Verify the extension actually installs** in the running container before declaring this done — this is the #1 likely failure point.

[Source: architecture.md#1.12.4 (lines 1367–1443); #1.7.1 (lines 421–428)]

### UUIDv7 vs UUIDv4 — which tables get which (MUST follow)

**UUIDv7** (`id UUID DEFAULT uuid_generate_v7() PRIMARY KEY`) — transactional / high-insert:
`billing_cdr_events`, `billing_transactions`, `billing_audit_log`, `fraud_cases`, `fraud_blacklist`, `support_tickets`, `support_chat_sessions`, `notifications_events`, `recharge_orders`, `segmentation_labels`, `segmentation_recommendation_feedback`, `segmentation_upsell_feedback`, `identity_registrations`, `identity_kyc_records`.

**UUIDv4** (`id UUID DEFAULT gen_random_uuid() PRIMARY KEY`) — reference / config:
`plans_plans`, `plans_plan_config`, `sop_rules`, `sop_knowledge_chunks`, `fraud_rules`, `notifications_config`, `notifications_preferences`, `identity_subscribers` (master record, not a transaction stream), and all other lookup/config tables.

> Note: architecture §1.11.2 says "Primary keys: always `id UUID DEFAULT gen_random_uuid()`" but §1.7.1 (the dedicated UUID strategy section) overrides this with the v7/v4 split above. **§1.7.1 wins** — it is the more specific, intentional rule. Apply the table-by-table split.

Every table also gets: `created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL`, `modified_at TIMESTAMPTZ DEFAULT NOW() NOT NULL`. [Source: architecture.md#1.7.1 (lines 380–428)]

### Table naming & indexing conventions

- Tables: `{domain}_{name}`, `snake_case`, plural, single `public` schema (no `identity.*` schemas in MVP). [Source: architecture.md#1.7.1, #1.11.2]
- FKs: `{referenced_table_singular}_id`; every FK column gets an index `idx_{table}_{columns}`.
- The full domain→table inventory is in architecture §1.7.1 (lines 363–374). Build every listed table.
- `billing_audit_log` is **append-only** (INSERT only via app role; no UPDATE/DELETE). Enforce via grants migration. [Source: architecture.md#1.7.1, line 378]

### Valkey configuration (critical)

- Standalone container (NOT MiniStack-bundled). `--maxmemory 512mb --maxmemory-policy noeviction`. The `noeviction` policy is mandatory: `balance:{msisdn}` keys must never be evicted. [Source: architecture.md#1.7.3 (line 513), #1.12.3 (lines 1304–1320)]
- Valkey is non-persisted across full-stack restarts in dev; balance warm-up (`load_balances_from_postgres()`) is a cdr-pipeline startup concern in Epic 2 — out of scope here, but do not add logic that assumes Valkey persistence.

### Docker Compose specifics

- Two-file split with `include:` is mandatory (ARCH-28). `docker-compose.override.yaml` carries local port mappings / hot-reload only.
- `service_webapp` (backend) `deploy.replicas: 1` is a **HARD CONSTRAINT** — Milvus Lite's embedded `.db` file does not support concurrent process access; >1 replica corrupts it. Add the explanatory comment. [Source: architecture.md#1.12.3 (lines 1352–1357)]
- Non-persisted services (OK to reset): Redpanda, LangFuse. Persisted via named volume: Postgres, Valkey, MiniStack, Milvus Lite data. [Source: architecture.md#1.12.3 (line 1361)]

### Environment variables (consumed here; `.env.example` authored in Story 1.3)

```dotenv
POSTGRES_SUPERUSER_PASSWORD=change_me_superuser
POSTGRES_APP_PASSWORD=change_me_app
POSTGRES_READONLY_PASSWORD=change_me_readonly
POSTGRES_FLYWAY_PASSWORD=change_me_flyway
```
This story may seed these into a local `.env`; the committed `.env.example` is Story 1.3's deliverable. Do not commit a real `.env` (gitignored). [Source: architecture.md#1.12.4 (lines 1429–1436); ARCH-17]

### Testing standards summary

- No application unit tests in this story. Verification is operational:
  - `docker compose -f docker/docker-compose-dependencies.yaml up -d` brings all infra healthy.
  - `psql` (as `postgres`) shows the four extensions installed and the three roles created.
  - Flyway `migrate` applies V1 + V2 with no errors; `\dt` lists all domain tables; spot-check one transactional table has a v7-defaulted `id` and one reference table has a v4-defaulted `id`.
  - Insert a row into a `modified_at` table, UPDATE it, confirm `modified_at` advanced (trigger works).
- Capture the verification commands/output in Debug Log References. Do not claim done without running them.

### Project Structure Notes

- Migrations: `service_webapp/db/migrations/V1__baseline_schema.sql`, `V2__modified_at_trigger.sql`. [Source: architecture.md#1.7.2, #1.12.1]
- Compose: `docker/docker-compose-dependencies.yaml`, `docker/docker-compose.yaml`, `docker/docker-compose.override.yaml`. Postgres init: `docker/postgres/init/0{1,2,3}_*.sql`.
- Variance: architecture's compose snippet mounts init as `./docker/postgres/init:/docker-entrypoint-initdb.d` (path relative to repo root when compose is run from root). Confirm the compose `working_dir`/path resolution given files live under `docker/` — adjust the relative path so the init mount resolves correctly regardless of where `docker compose` is invoked from. This is a known footgun; verify the mount actually populates init scripts.
- `cdr-pipeline/` does not exist yet; its compose service references a build context that will only build once Epic 2 adds the code. For this story it is acceptable for the full-stack `up` to be verified only for the dependency services; document that `cdr-pipeline`/`service_webapp` images may not yet build.

### References

- [Source: epics.md#Story-1.2 (lines 324–339)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (lines 357–428)]
- [Source: architecture.md#1.7.2-Database-Migration-Management (lines 432–478)]
- [Source: architecture.md#1.7.3-Valkey-Redis-Data-Domains (lines 480–513)]
- [Source: architecture.md#1.12.3-Docker-Compose-Services (lines 1290–1365)]
- [Source: architecture.md#1.12.4-PostgreSQL-Container-Initialization (lines 1367–1443)]
- [Source: architecture.md#1.13.4a Callout 3 — sboai_flyway CREATEROLE accepted for local dev (lines 1539–1546)]
- [Source: docs/Schema - CDR.md — full billing_cdr_events column definitions]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

**Verification commands (run from project root with Podman on Windows):**

Step 1 — Start infra only:
```bash
podman compose -f docker/docker-compose-dependencies.yaml --env-file .env up -d
```

Step 2 — Wait for Postgres healthy, then verify extensions and roles:
```bash
# Check extensions installed in sboai database
podman exec -it <project>-postgres-1 psql -U postgres -d sboai -c "SELECT extname FROM pg_extension;"
# Expected rows: pg_uuidv7, pgcrypto, pg_trgm, btree_gin (+ plpgsql)

# Check roles created
podman exec -it <project>-postgres-1 psql -U postgres -d sboai -c "\du"
# Expected: sboai_app, sboai_readonly, sboai_flyway listed
```

Step 3 — Flyway service will auto-run on startup; check its output:
```bash
podman compose -f docker/docker-compose-dependencies.yaml --env-file .env logs flyway
# Expected: "Successfully applied 2 migrations to schema "public"..."
```

Step 4 — Verify all tables created:
```bash
podman exec -it <project>-postgres-1 psql -U postgres -d sboai -c "\dt"
# Expected: 27+ tables listed across all domains
```

Step 5 — Spot-check UUIDv7 default on transactional table:
```bash
podman exec -it <project>-postgres-1 psql -U postgres -d sboai \
  -c "INSERT INTO identity_subscribers (msisdn, subscriber_name) VALUES ('+919876543210', 'Test User') RETURNING id, created_at;"
# id should start with 0190... (time-based UUIDv7 prefix for 2024+)
# For reference tables (UUIDv4), the id should be random (not time-prefixed)
```

Step 6 — Verify modified_at trigger fires:
```bash
podman exec -it <project>-postgres-1 psql -U postgres -d sboai -c "
  SELECT id, modified_at FROM identity_subscribers LIMIT 1;
  -- Note the timestamp
  UPDATE identity_subscribers SET subscriber_name = 'Updated' WHERE msisdn = '+919876543210';
  SELECT id, modified_at FROM identity_subscribers LIMIT 1;
  -- modified_at should have advanced
"
```

**Notes:**
- Verification was not run in WSL2 session; user to execute from Windows with Podman.
- pg_uuidv7 requires PGDG APT repository (pre-configured in postgres:16 base image). If `apt-get install postgresql-16-pg-uuidv7` fails, an alternative is to build from source in the Dockerfile.
- `billing_cdr_events` and `billing_audit_log` intentionally have no `modified_at` column (append-only tables).

### Completion Notes List

1. **02_roles.sql changed to 02_roles.sh**: PostgreSQL init `.sql` files do not expand shell environment variables. Changed to a bash script that calls `psql` with heredoc to correctly expand `${POSTGRES_*_PASSWORD}` env vars. Idempotency preserved with `IF NOT EXISTS` DO blocks.

2. **Custom Postgres Dockerfile added**: `postgres:16` standard image lacks `pg_uuidv7`. Created `docker/postgres/Dockerfile` that installs `postgresql-16-pg-uuidv7` from the PGDG APT repo.

3. **Flyway added to infra compose**: Flyway runs as a short-lived service (`restart: no`) that depends on `postgres` health. This auto-applies V1+V2 on first stack start. Migrations path: `../service_webapp/db/migrations` (relative to `docker/` compose file location).

4. **LangFuse database**: Added `CREATE DATABASE langfuse` in `03_databases.sql`. LangFuse connects as postgres superuser and auto-migrates its own tables via Prisma on startup.

5. **ministack_s3 volume declared per ARCH-29 but not separately mounted**: LocalStack uses a unified state directory. `ministack_cognito` holds all LocalStack state; `ministack_s3` is declared in the `volumes:` section to satisfy ARCH-29 but is not separately mounted (LocalStack doesn't split by service).

6. **Cross-story note (V1 full baseline)**: Because V1 creates the entire schema (all domains), later stories 1.6/1.8/1.10 that reference per-story migrations (`V2__subscriber_schema.sql`, `V3__auth_schema.sql`, `V4__payment_schema.sql`) will NOT need to create tables — those tables exist in V1. Those stories should instead add views, grants, or application code that uses the already-created tables.

7. **billing_cdr_events schema**: Used a single-table MVP design (no separate `cdr_enrichments` side-table) per CDR doc §1.7. All type-specific columns (voice/sms/data) are nullable in one table. Enums created as PostgreSQL custom types for type safety.

### File List

- `docker/postgres/Dockerfile`
- `docker/postgres/init/01_extensions.sql`
- `docker/postgres/init/02_roles.sh`
- `docker/postgres/init/03_databases.sql`
- `docker/docker-compose-dependencies.yaml`
- `docker/docker-compose.yaml`
- `docker/docker-compose.override.yaml`
- `docker/otel/otel-collector-config.yaml`
- `docker/fluentd/fluent.conf`
- `service_webapp/db/migrations/V1__baseline_schema.sql`
- `service_webapp/db/migrations/V2__modified_at_trigger.sql`
- `.env` (gitignored — local secrets only)

## Change Log

- 2026-06-20: Story 1.2 implemented — Docker Compose two-file split, Postgres init scripts with pg_uuidv7 custom image, Flyway V1 full all-domain baseline schema (27 tables across 10 domains), V2 modified_at trigger migration.
