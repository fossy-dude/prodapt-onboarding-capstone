#!/usr/bin/env bash
# Milvus Lite seeder (Story 2.7; AC #4-7)
# Runs after `just seed` — plans_plans and sop_knowledge_chunks must be populated first.
# Override AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / MILVUS_DB_URI in the environment
# before running if the defaults in .env are placeholders.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_PASS=$(grep '^POSTGRES_APP_PASSWORD=' "${PROJECT_ROOT}/docker/.env" | cut -d= -f2)

export DB__HOST="${DB__HOST:-localhost}"
export DB__PORT="${DB__PORT:-5432}"
export DB__NAME="${DB__NAME:-sboai}"
export DB__USER="${DB__USER:-sboai_app}"
export DB__PASSWORD="${DB__PASSWORD:-${APP_PASS}}"
export VALKEY_URL="${VALKEY_URL:-redis://localhost:6379}"
export KAFKA_BROKERS="${KAFKA_BROKERS:-localhost:9092}"

# Milvus Lite path — local dev uses a path relative to project root.
export MILVUS_DB_URI="${MILVUS_DB_URI:-${PROJECT_ROOT}/data/milvus/sboai.db}"
mkdir -p "$(dirname "${MILVUS_DB_URI}")"

export PYTHONPATH="${PROJECT_ROOT}/service_webapp/src"

echo "[seed-milvus] Seeding Milvus Lite at ${MILVUS_DB_URI} ..."
uv run --no-project \
    --with "psycopg[binary]>=3.2" \
    --with "pydantic-settings>=2.3" \
    --with "pymilvus[milvus-lite]>=2.5" \
    --with "langchain-openai>=0.2" \
    --with "pyyaml>=6" \
    python3 "${SCRIPT_DIR}/seed_milvus.py"

echo "[seed-milvus] Done."
