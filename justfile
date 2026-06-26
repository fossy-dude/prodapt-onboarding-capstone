# SBOAI Capstone — cross-platform task runner.
#
# Run `just --list` to see every recipe. The backend dir is `service_webapp/`
# (the architecture's `service_webapp`/`app-backend` both resolve to it).
# See README.md §4 (Development Workflow) and architecture.md §1.12.2.

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]
set dotenv-load := true
set dotenv-path := "docker/.env"

# tox is run through `uv` via the tox-uv plugin (it provides `uv-venv-runner`).
# NOTE: architecture.md §1.12.2 documents `uv tox`, but that is not a real `uv`
# subcommand (uv 0.11.x). `uvx --with tox-uv tox` achieves the same tox-via-uv
# intent without requiring a global tox install. See Story 1.3 Completion Notes.
uv_tox := "uvx --with tox-uv tox"

# Default: print the recipe list so `just` with no args is helpful, not cryptic.
default:
    @just --list

# Check that every named environment variable is non-empty.
# Accumulates all missing names before exiting so callers see the full error list at once.
[private]
_check-env *vars:
    #!/usr/bin/env bash
    vars="{{vars}}"
    [[ -z "$vars" ]] && exit 0
    missing=()
    for var in $vars; do
        [[ -z "${!var:-}" ]] && missing+=("$var")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: The following required environment variables are not set (check docker/.env):"
        printf '  - %s\n' "${missing[@]}"
        exit 1
    fi

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
    just _check-env POSTGRES_FLYWAY_USERNAME POSTGRES_FLYWAY_PASSWORD
    podman run --rm \
        --network host \
        -e FLYWAY_URL=jdbc:postgresql://localhost:5432/sboai \
        -e "FLYWAY_USER=${POSTGRES_FLYWAY_USERNAME}" \
        -e "FLYWAY_PASSWORD=${POSTGRES_FLYWAY_PASSWORD}" \
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
    just _check-env DB__HOST DB__PORT DB__NAME DB__USER DB__PASSWORD SEED_ADMIN_USER SEED_ADMIN_PASSWORD VALKEY_URL KAFKA_BROKERS
    SCRIPTS="{{ justfile_directory() }}/scripts"
    # --no-project: skip editable install (project uses package=skip in tox; not a buildable package).
    # project deps (psycopg, pydantic-settings) pulled via --with; seed-only deps (numpy/pandas/faker) also via --with.
    echo "[seed] Seeding plans + subscribers + CDRs ..."
    PYTHONPATH="{{ justfile_directory() }}/service_webapp/src" uv run --no-project \
        --with "psycopg[binary]>=3.2" --with "pydantic-settings>=2.3" \
        --with "numpy>=1.26" --with "pandas>=2.0" --with "faker>=26" \
        python3 "${SCRIPTS}/generate_synthetic_data.py" --skip-truncate-if-pre-seeded
    echo "[seed] Seeding SOP knowledge base ..."
    PYTHONPATH="{{ justfile_directory() }}/service_webapp/src" uv run --no-project \
        --with "psycopg[binary]>=3.2" --with "pydantic-settings>=2.3" \
        python3 "${SCRIPTS}/sop_generator.py"
    echo "[seed] Done. Fraud demo report: scripts/fraud_report.json"

# Ingest FAQ/plan/SOP documents into Milvus Lite (Story 2.7; AC #4-7).
# Run `just seed` first — plans_plans and sop_knowledge_chunks must be populated.
# Override AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / MILVUS_DB_URI in environment
# before running if the .env values are placeholders.
seed-milvus:
    just -d service_webapp -f service_webapp/justfile seed-milvus

# ── Dev servers ──────────────────────────────────────────────────────────────────
# Run the backend dev server via service_webapp/justfile.
run-dev-backend:
    just -d service_webapp -f service_webapp/justfile dev

# Run the frontend dev server via frontend/justfile.
run-dev-frontend:
    just -d frontend -f frontend/justfile dev

# Run the CDR pipeline consumer (Story 2.2). Consumer + management API on port 8001 (Story 2.5).
run-dev-cdr:
    @[ -f cdr-pipeline/src/__init__.py ] || (touch cdr-pipeline/src/__init__.py && echo "Created src/__init__.py")
    cd cdr-pipeline && PYTHONPATH=src python -m main

# Run the CDR management API standalone (Story 2.5). Admin endpoints on port 8001.
# Requires COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID set in environment or .env.
run-dev-cdr-admin:
    @echo "→ CDR management API: http://localhost:8001/api/v1/admin/dlq"
    cd cdr-pipeline && PYTHONPATH=src python -m main

# ── Tests ────────────────────────────────────────────────────────────────────────

# Run all tests
test:
    just -d service_webapp -f service_webapp/justfile test
    just -d cdr-pipeline -f cdr-pipeline/justfile test
    just -d frontend -f frontend/justfile test

# Run backend integration tests (opt-in; integration/slow are skipped by default).
test-integration:
    cd service_webapp && {{uv_tox}} -e test -- --run-integration

# Run CDR pipeline integration tests (opt-in).
test-cdr-integration:
    cd cdr-pipeline && {{uv_tox}} -e test -- --run-integration

# Run the chatbot eval suite (LLM-as-Judge + DeepEval). Requires AZURE_OPENAI_*
# env vars; exits non-zero if quality thresholds are not met. (Story 5.2)
eval:
    just -d service_webapp -f service_webapp/justfile eval

# Run frontend unit tests (Vitest).
test-fe:
    

# ── Quality gate ─────────────────────────────────────────────────────────────────

# Lint both Python codebases + frontend (ruff lint + ruff format check + pyrefly type check + ESLint).
lint:
    just -d service_webapp -f service_webapp/justfile lint
    just -d cdr-pipeline -f cdr-pipeline/justfile lint
    just -d frontend -f frontend/justfile lint

# Full quality gate (lint + test) for both Python codebases.
tox:
    cd service_webapp && {{uv_tox}} && cd ../cdr-pipeline && {{uv_tox}}

# Auto-format all codebases (ruff format + Prettier).
format:
    just -d service_webapp -f service_webapp/justfile format
    just -d cdr-pipeline -f cdr-pipeline/justfile format
    just -d frontend -f frontend/justfile format


# Monitoring
monitor_otel:
    podman attach otel-tui