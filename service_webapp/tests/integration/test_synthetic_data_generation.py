"""Integration tests for Story 2.6 synthetic data generation.

Requires a container runtime (Docker/Podman). Marked ``slow`` + ``integration``.
Run with: DOCKER_HOST=unix:///run/user/1000/podman/podman.sock pytest -m slow

Uses env overrides for reduced scale:
    SUBSCRIBER_COUNT=500 CDR_COUNT=5000 pytest -m slow ...
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "db" / "migrations"
SEED_SQL = Path(__file__).parent.parent.parent / "db" / "seed" / "seed_plans.sql"
SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"

# Reduced-scale defaults for CI (overridable via env)
SUBSCRIBER_COUNT = int(os.getenv("SUBSCRIBER_COUNT", "500"))
CDR_COUNT = int(os.getenv("CDR_COUNT", "5000"))


@pytest.fixture(scope="module")
def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16") as container:
        yield container


@pytest.fixture(scope="module")
def pg_conninfo(pg: PostgresContainer) -> str:
    return (
        f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} user={pg.username} password={pg.password}"
    )


def _apply_migrations(pg_conninfo: str) -> None:
    """Apply V1..V4 migrations using psql (Flyway not available in test containers)."""
    for migration in sorted(MIGRATIONS_DIR.glob("V*.sql")):
        sql = migration.read_text()
        with psycopg.connect(pg_conninfo, autocommit=True) as conn:
            # Enable required extensions
            if "V1" in migration.name:
                try:
                    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                    conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
                    # uuid_generate_v7 is from pg_uuidv7; not available in plain postgres:16
                    # Create a stub so V1 DDL parses without error in tests
                    conn.execute(
                        "CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid "
                        "LANGUAGE sql AS $$ SELECT gen_random_uuid() $$"
                    )
                except Exception:
                    pass
            try:
                conn.execute(sql)
            except Exception as exc:
                # Some migrations may fail if already applied; ignore idempotent ones
                if "already exists" not in str(exc).lower():
                    raise


def _run_generators(pg_conninfo: str) -> None:
    """Run generate_synthetic_data.py + sop_generator.py at reduced scale."""
    env = os.environ.copy()
    env["SUBSCRIBER_COUNT"] = str(SUBSCRIBER_COUNT)
    env["CDR_COUNT"] = str(CDR_COUNT)
    env["SEED"] = "42"

    # Parse conninfo into env vars that core.config expects
    parts = dict(kv.split("=", 1) for kv in pg_conninfo.split())
    env["DB__HOST"] = parts.get("host", "localhost")
    env["DB__PORT"] = parts.get("port", "5432")
    env["DB__NAME"] = parts.get("dbname", "test")
    env["DB__USER"] = parts.get("user", "test")
    env["DB__PASSWORD"] = parts.get("password", "test")
    env["VALKEY_URL"] = "redis://localhost:6379"
    env["KAFKA_BROKERS"] = "localhost:9092"
    env["FRAUD_REPORT_PATH"] = str(Path("/tmp") / "fraud_report_test.json")

    src_path = str(SCRIPTS_DIR.parent / "service_webapp" / "src")
    env["PYTHONPATH"] = src_path

    script = str(SCRIPTS_DIR / "generate_synthetic_data.py")
    result = subprocess.run(
        [sys.executable, script],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"generate_synthetic_data.py failed:\n{result.stderr}"

    sop_script = str(SCRIPTS_DIR / "sop_generator.py")
    result = subprocess.run(
        [sys.executable, sop_script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"sop_generator.py failed:\n{result.stderr}"


@pytest.fixture(scope="module")
def seeded_db(pg: PostgresContainer, pg_conninfo: str):
    """Apply migrations + run generators once for the module."""
    _apply_migrations(pg_conninfo)
    _run_generators(pg_conninfo)
    return pg_conninfo


def test_plan_count(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM plans_plans").fetchone()[0]
    assert count == 1000, f"Expected 1000 plans, got {count}"


def test_subscriber_count(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM identity_subscribers").fetchone()[0]
    assert count == SUBSCRIBER_COUNT, f"Expected {SUBSCRIBER_COUNT} subscribers, got {count}"


def test_cdr_count(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM billing_cdr_events").fetchone()[0]
    assert count == CDR_COUNT, f"Expected {CDR_COUNT} CDRs, got {count}"


def test_wallet_count(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM billing_wallet_balances").fetchone()[0]
    assert count == SUBSCRIBER_COUNT, f"Expected {SUBSCRIBER_COUNT} wallets, got {count}"


def test_subscriber_plan_id_fk_valid(seeded_db: str) -> None:
    """Every subscriber's plan_id must reference an existing plan."""
    with psycopg.connect(seeded_db) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM identity_subscribers s "
            "WHERE s.plan_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM plans_plans p WHERE p.id = s.plan_id)"
        ).fetchone()[0]
    assert orphans == 0, f"{orphans} subscribers have invalid plan_id"


def test_cdr_subscriber_id_fk_valid(seeded_db: str) -> None:
    """Every CDR's subscriber_id must reference an existing subscriber."""
    with psycopg.connect(seeded_db) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM billing_cdr_events c "
            "WHERE NOT EXISTS (SELECT 1 FROM identity_subscribers s WHERE s.id = c.subscriber_id)"
        ).fetchone()[0]
    assert orphans == 0, f"{orphans} CDRs have invalid subscriber_id"


def test_cdr_type_distribution(seeded_db: str) -> None:
    """CDR type distribution should be ≈ voice 60% / data 30% / SMS 10% (±5 pp tolerance)."""
    with psycopg.connect(seeded_db) as conn:
        rows = conn.execute("SELECT cdr_type, COUNT(*) FROM billing_cdr_events GROUP BY cdr_type").fetchall()
    total = sum(r[1] for r in rows)
    dist = {r[0]: r[1] / total for r in rows}

    assert 0.55 <= dist.get("voice", 0) <= 0.65, f"Voice: {dist.get('voice', 0):.2%}"
    assert 0.25 <= dist.get("data", 0) <= 0.35, f"Data: {dist.get('data', 0):.2%}"
    assert 0.05 <= dist.get("sms", 0) <= 0.15, f"SMS: {dist.get('sms', 0):.2%}"


def test_fraud_flagged_fraction(seeded_db: str) -> None:
    """Approximately 0.5% of subscribers should have at least one fraud-flagged CDR."""
    with psycopg.connect(seeded_db) as conn:
        sub_count = conn.execute("SELECT COUNT(*) FROM identity_subscribers").fetchone()[0]
        fraud_sub_count = conn.execute(
            "SELECT COUNT(DISTINCT subscriber_id) FROM billing_cdr_events WHERE fraud_flag = TRUE"
        ).fetchone()[0]

    fraction = fraud_sub_count / sub_count
    # Allow wide tolerance at reduced scale (500 subs → ~3 fraud subs)
    assert fraction > 0, "No fraud-flagged CDRs found"
    assert fraction < 0.05, f"Fraud fraction too high: {fraction:.2%}"


def test_voice_cdr_has_required_fields(seeded_db: str) -> None:
    """Voice CDRs must have from_number, to_number, call_direction, duration_seconds, call_status."""
    with psycopg.connect(seeded_db) as conn:
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM billing_cdr_events "
            "WHERE cdr_type = 'voice' AND ("
            "  from_number IS NULL OR to_number IS NULL OR "
            "  call_direction IS NULL OR duration_seconds IS NULL OR call_status IS NULL"
            ")"
        ).fetchone()[0]
    assert incomplete == 0, f"{incomplete} voice CDRs missing required fields"


def test_sms_cdr_has_required_fields(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM billing_cdr_events "
            "WHERE cdr_type = 'sms' AND (message_direction IS NULL OR sms_status IS NULL)"
        ).fetchone()[0]
    assert incomplete == 0, f"{incomplete} SMS CDRs missing required fields"


def test_data_cdr_has_required_fields(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM billing_cdr_events "
            "WHERE cdr_type = 'data' AND ("
            "  network_type IS NULL OR volume_mb IS NULL OR apn IS NULL"
            ")"
        ).fetchone()[0]
    assert incomplete == 0, f"{incomplete} data CDRs missing required fields"


def test_cost_paise_not_negative(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        neg = conn.execute("SELECT COUNT(*) FROM billing_cdr_events WHERE cost_paise < 0").fetchone()[0]
    assert neg == 0, f"{neg} CDRs have negative cost_paise"


def test_idempotency(pg: PostgresContainer, pg_conninfo: str, seeded_db: str) -> None:
    """Re-running generators yields the same row counts (truncate + reseed)."""
    _run_generators(pg_conninfo)

    with psycopg.connect(pg_conninfo) as conn:
        plans = conn.execute("SELECT COUNT(*) FROM plans_plans").fetchone()[0]
        subs = conn.execute("SELECT COUNT(*) FROM identity_subscribers").fetchone()[0]
        cdrs = conn.execute("SELECT COUNT(*) FROM billing_cdr_events").fetchone()[0]

    assert plans == 1000
    assert subs == SUBSCRIBER_COUNT
    assert cdrs == CDR_COUNT


def test_sop_rules_seeded(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sop_rules").fetchone()[0]
    assert count >= 10, f"Expected ≥10 SOP rules, got {count}"


def test_sop_chunks_seeded(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sop_knowledge_chunks").fetchone()[0]
    assert count >= 20, f"Expected ≥20 SOP knowledge chunks, got {count}"


def test_sop_domains_populated(seeded_db: str) -> None:
    with psycopg.connect(seeded_db) as conn:
        domains = {r[0] for r in conn.execute("SELECT DISTINCT domain FROM sop_knowledge_chunks").fetchall()}
    expected = {"billing", "fraud", "activation", "support", "compliance", "network"}
    assert expected.issubset(domains), f"Missing domains: {expected - domains}"
