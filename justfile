# SBOAI Capstone — cross-platform task runner.
#
# Run `just --list` to see every recipe. The backend dir is `service_webapp/`
# (the architecture's `service_backend`/`app-backend` both resolve to it).
# See README.md §4 (Development Workflow) and architecture.md §1.12.2.

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

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
    podman compose -f docker/docker-compose-dependencies.yaml --env-file docker/.env up -d

# Start the full application stack (infra + cdr-pipeline + service_webapp + frontend).
up:
    podman compose -f docker/docker-compose.yaml --env-file docker/.env up -d

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
migrate:
    flyway -url=jdbc:postgresql://localhost:5432/sboai -locations=filesystem:service_webapp/db/migrations migrate

# Generate synthetic data (1K plans -> 300K subscribers -> 5M CDRs). Script lands in Epic 2.
seed:
    @echo "[seed] Synthetic data generation lands in Epic 2 (scripts/generate_synthetic_data.py)."
    @echo "[seed] This recipe is wired now so the README and CI reference a stable command."
    @exit 1

# Ingest FAQ/plan/SOP documents into Milvus Lite. Script lands in Epic 2.
# (architecture §1.12.2 erroneously ran the .sh with python; corrected to bash.)
seed-milvus:
    @echo "[seed-milvus] Milvus seeding lands in Epic 2 (scripts/seed_milvus.sh)."
    @echo "[seed-milvus] Note: architecture 1.12.2 ran the .sh via python; corrected to bash."
    @exit 1

# ── Dev servers ──────────────────────────────────────────────────────────────────

# Run the backend dev server (FastAPI/uvicorn) with hot reload. App wired in Story 1.4.
backend:
    cd service_webapp && uvicorn src.main:app --reload --port 8000

# Run the frontend dev server (Vite).
frontend:
    cd frontend && npm run dev

# Run the CDR pipeline consumer. Consumer lands in Epic 2.
cdr:
    cd cdr-pipeline && python -m src.main

# ── Tests ────────────────────────────────────────────────────────────────────────

# Run backend tests (service_webapp).
test:
    cd service_webapp && {{uv_tox}} -e test

# Run CDR pipeline tests.
test-cdr:
    cd cdr-pipeline && {{uv_tox}} -e test

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
    cd service_webapp && uvx ruff format src/ && cd ../cdr-pipeline && uvx ruff format src/
