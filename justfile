# SBOAI Capstone — cross-platform task runner.
#
# Run `just --list` to see every recipe. The backend dir is `service_webapp/`
# (the architecture's `service_webapp`/`app-backend` both resolve to it).
# See README.md §4 (Development Workflow) and architecture.md §1.12.2.

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]
set dotenv-load := true
set dotenv-path := "service_webapp/.env"

# tox is run through `uv` via the tox-uv plugin (it provides `uv-venv-runner`).
# NOTE: architecture.md §1.12.2 documents `uv tox`, but that is not a real `uv`
# subcommand (uv 0.11.x). `uvx --with tox-uv tox` achieves the same tox-via-uv
# intent without requiring a global tox install. See Story 1.3 Completion Notes.
uv_tox := "uvx --with tox-uv tox"

# Default: print the recipe list so `just` with no args is helpful, not cryptic.
default:
    @just --list

# ── Dependencies / infrastructure (Podman) ───────────────────────────────────────

# Start infrastructure-only stack (Postgres, Redpanda, Valkey, LangFuse, OTEL, Fluentd).
deps:
    @[ -f docker/.env ] || { echo "ERROR: docker/.env not found. Run: cp .env.example docker/.env"; exit 1; }
    @grep -q "change_me" docker/.env && { echo "ERROR: docker/.env contains placeholder passwords. Edit the file with real values."; exit 1; } || true
    podman compose -f docker/docker-compose-dependencies.yaml --env-file docker/.env up -d
    @echo "→ LangFuse dashboard: http://localhost:3000  (Story 1.5; login via LANGFUSE_INIT_USER_* in docker/.env)"
    @i=0; until podman exec redpanda rpk cluster health > /dev/null 2>&1 || [ $i -ge 60 ]; do i=$((i+1)); sleep 1; done; if [ $i -ge 60 ]; then echo "ERROR: Redpanda health check timeout after 60s"; exit 1; fi
    @just provision-topics
    @just provision-cognito
    @i=0; until podman exec postgres pg_isready -U sboai_superuser > /dev/null 2>&1 || [ $i -ge 60 ]; do i=$((i+1)); sleep 1; done; if [ $i -ge 60 ]; then echo "ERROR: Postgres health check timeout after 60s"; exit 1; fi
    @just migrate
    @just seed
    @just seed-milvus

# Provision MiniStack Cognito (user pool, role groups, app client, demo users). Idempotent.
# Runs automatically after `just deps`; safe to re-run by hand. Writes pool/client IDs
# into service_webapp/.env and seeded-user identities into README.md.
provision-cognito:
    @command -v uvx > /dev/null || { echo "ERROR: uv not installed. See README §1 prerequisites."; exit 1; }
    uvx --with boto3 python scripts/provision_cognito.py

# Provision the CDR pipeline Kafka/Redpanda topics (idempotent — AC #2). Runs
# automatically after Redpanda is healthy via `just up` / `just deps`; safe to
# re-run by hand once the stack is up. Host-script pattern mirrors provision-cognito.
# NOTE: If provisioning fails, Redpanda auto-creates topics with 1 partition (not 24).
provision-topics:
    @command -v uvx > /dev/null || { echo "ERROR: uv not installed. See README §1 prerequisites."; exit 1; }
    @cd cdr-pipeline && PYTHONPATH=src uvx --with aiokafka --with pydantic --with pydantic-settings --with uuid7 python scripts/provision_topics.py \
    || { \
    echo "WARN: topic provisioning failed; topics will be auto-created with 1 partition (consumer parallelism may be impacted)."; \
    echo "Re-run manually: just provision-topics"; \
    }

# Destroy infrastructure-only stack (stop containers, remove volumes and networks).
deps_destroy:
    podman compose -f docker/docker-compose-dependencies.yaml down -v --remove-orphans

# Start the full application stack (infra + cdr-pipeline + service_webapp + frontend).
up:
    @[ -f docker/.env ] || { echo "ERROR: docker/.env not found. Run: cp .env.example docker/.env"; exit 1; }
    @until podman exec postgres pg_isready -U sboai_superuser > /dev/null 2>&1; do sleep 1; done
    podman compose -f docker/docker-compose.yaml --env-file docker/.env up -d
    @i=0; until podman exec redpanda rpk cluster health > /dev/null 2>&1 || [ $i -ge 60 ]; do i=$((i+1)); sleep 1; done; if [ $i -ge 60 ]; then echo "ERROR: Redpanda health check timeout after 60s"; exit 1; fi
    @just provision-topics
    @echo "→ LangFuse dashboard: http://localhost:3000  (requires 'just deps' first; login via LANGFUSE_INIT_USER_* in docker/.env)"

# Stop the full application stack.
down:
    podman compose -f docker/docker-compose.yaml down

# Tail logs for the full stack.
logs:
    podman compose -f docker/docker-compose.yaml logs -f

# Restart a single service, e.g. `just restart service_webapp`.
restart svc:
    podman compose -f docker/docker-compose.yaml restart {{svc}}

# ── Database ─────────────────────────────────────────────────────────────────────

# Apply Flyway migrations against the local `sboai` database (Postgres must be up).
# Runs flyway/flyway:10-alpine via podman (--network host reaches the published postgres port).
# Credentials sourced from docker/.env (POSTGRES_FLYWAY_USERNAME / POSTGRES_FLYWAY_PASSWORD).
migrate:
    #!/usr/bin/env bash
    set -euo pipefail
    FW_USER=$(grep '^POSTGRES_FLYWAY_USERNAME=' docker/.env | cut -d= -f2)
    FW_PASS=$(grep '^POSTGRES_FLYWAY_PASSWORD=' docker/.env | cut -d= -f2)
    podman run --rm \
        --network host \
        -e FLYWAY_URL=jdbc:postgresql://localhost:5432/sboai \
        -e "FLYWAY_USER=${FW_USER}" \
        -e "FLYWAY_PASSWORD=${FW_PASS}" \
        -e FLYWAY_SCHEMAS=public \
        -e FLYWAY_CONNECT_RETRIES=10 \
        -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
        -e FLYWAY_CLEAN_DISABLED=true \
        -v "{{ justfile_directory() }}/service_webapp/db/migrations:/flyway/sql:ro" \
        docker.io/flyway/flyway:10-alpine \
        migrate

# Seed synthetic data: 1K plans (service_webapp/db/seed/) + 300K subscribers + 5M CDRs + SOP knowledge base.
# Plans seed SQL is executed by generate_synthetic_data.py (NOT Flyway).
# Writes scripts/fraud_report.json listing fraudulent subscribers for demo.
# Idempotent: safe to re-run (truncates generated tables, re-seeds plans via ON CONFLICT).
# DB credentials sourced from docker/.env (sboai_app / POSTGRES_APP_PASSWORD).
seed:
    #!/usr/bin/env bash
    set -euo pipefail
    APP_PASS=$(grep '^POSTGRES_APP_PASSWORD=' docker/.env | cut -d= -f2)
    export DB__HOST=localhost
    export DB__PORT=5432
    export DB__NAME=sboai
    export DB__USER=sboai_app
    export DB__PASSWORD="${APP_PASS}"
    export VALKEY_URL=redis://localhost:6379
    export KAFKA_BROKERS=localhost:9092
    SCRIPTS="{{ justfile_directory() }}/scripts"
    export PYTHONPATH="{{ justfile_directory() }}/service_webapp/src"
    # --no-project: skip editable install (project uses package=skip in tox; not a buildable package).
    # project deps (psycopg, pydantic-settings) pulled via --with; seed-only deps (numpy/pandas/faker) also via --with.
    echo "[seed] Seeding plans + subscribers + CDRs ..."
    uv run --no-project \
        --with "psycopg[binary]>=3.2" --with "pydantic-settings>=2.3" \
        --with "numpy>=1.26" --with "pandas>=2.0" --with "faker>=26" \
        python3 "${SCRIPTS}/generate_synthetic_data.py"
    echo "[seed] Seeding SOP knowledge base ..."
    uv run --no-project \
        --with "psycopg[binary]>=3.2" --with "pydantic-settings>=2.3" \
        python3 "${SCRIPTS}/sop_generator.py"
    echo "[seed] Done. Fraud demo report: scripts/fraud_report.json"

# Ingest FAQ/plan/SOP documents into Milvus Lite (Story 2.7; AC #4-7).
# Run `just seed` first — plans_plans and sop_knowledge_chunks must be populated.
# Override AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / MILVUS_DB_URI in environment
# before running if the .env values are placeholders.
seed-milvus:
    bash scripts/seed_milvus.sh

# ── Dev servers ──────────────────────────────────────────────────────────────────

# Run the backend dev server (FastAPI/uvicorn) with hot reload.
# PYTHONPATH=src is required so ``src.main`` resolves AND the app's top-level
# internal imports (``core``/``routers``/``adapters``) match the [tool.pytest]
# pythonpath=["src"] layout. cwd stays at service_webapp/ so config's
# ``env_file=".env"`` still loads service_webapp/.env. (Story 1.4.)
backend:
    cd service_webapp && PYTHONPATH=src uvicorn src.main:app --reload --port 8000

# Run the frontend dev server (Vite).
frontend:
    @[ -d frontend/node_modules ] || (cd frontend && npm ci && echo "Dependencies installed")
    cd frontend && npm run dev

# Run the CDR pipeline consumer (Story 2.2). Consumer + management API on port 8001 (Story 2.5).
cdr:
    @[ -f cdr-pipeline/src/__init__.py ] || (touch cdr-pipeline/src/__init__.py && echo "Created src/__init__.py")
    cd cdr-pipeline && PYTHONPATH=src python -m main

# Run the CDR management API standalone (Story 2.5). Admin endpoints on port 8001.
# Requires COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID set in environment or .env.
cdr-admin:
    @echo "→ CDR management API: http://localhost:8001/api/v1/admin/dlq"
    cd cdr-pipeline && PYTHONPATH=src python -m main

# ── Tests ────────────────────────────────────────────────────────────────────────

# Run backend tests (service_webapp).
test:
    cd service_webapp && {{uv_tox}} -e test

# Run CDR pipeline tests.
test-cdr:
    cd cdr-pipeline && {{uv_tox}} -e test

# Run backend integration tests (opt-in; integration/slow are skipped by default).
test-integration:
    cd service_webapp && {{uv_tox}} -e test -- --run-integration

# Run CDR pipeline integration tests (opt-in).
test-cdr-integration:
    cd cdr-pipeline && {{uv_tox}} -e test -- --run-integration

# Run frontend unit tests (Vitest).
test-fe:
    cd frontend && npm run test

# ── Quality gate ─────────────────────────────────────────────────────────────────

# Lint both Python codebases (ruff lint + ruff format check + pyrefly type check).
lint:
    cd service_webapp && {{uv_tox}} -e lint && cd ../cdr-pipeline && {{uv_tox}} -e lint

# Lint the frontend (ESLint).
lint-fe:
    cd frontend && npm run lint

# Full quality gate (lint + test) for both Python codebases.
tox:
    cd service_webapp && {{uv_tox}} && cd ../cdr-pipeline && {{uv_tox}}

# Auto-format both Python codebases (ruff format).
format:
    @command -v uvx > /dev/null || { echo "ERROR: uv not installed. See README prerequisites."; exit 1; }
    @mkdir -p service_webapp/src cdr-pipeline/src
    cd service_webapp && uvx ruff format src/ && cd ../cdr-pipeline && uvx ruff format src/


# Monitoring
just monitor_otel:
    podman attach otel-tui