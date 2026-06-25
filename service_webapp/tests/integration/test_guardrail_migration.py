"""Integration test for V8 support_guardrail_rejections migration (Story 5.5 Task 1).

Validates that V8__support_guardrail_rejections.sql creates the correct table structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from testcontainers.postgres import PostgresContainer

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "db" / "migrations"

pytestmark = [pytest.mark.slow, pytest.mark.integration]


@pytest.fixture(scope="module")
def pg() -> PostgresContainer:
    """Fresh Postgres container for migration testing."""
    with PostgresContainer("postgres:16") as container:
        yield container


@pytest.fixture(scope="module")
def pg_conninfo(pg: PostgresContainer) -> str:
    """Get connection string from test container."""
    return (
        f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} user={pg.username} password={pg.password}"
    )


def _apply_v8_migration(pg_conninfo: str) -> None:
    """Apply V8 migration with required extensions."""
    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Enable required extensions
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        # Create stub for uuid_generate_v7 (not available in plain postgres:16)
        conn.execute(
            "CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid LANGUAGE sql AS $$ SELECT gen_random_uuid() $$"
        )

        # Read and execute V8 migration
        migration_path = MIGRATIONS_DIR / "V8__support_guardrail_rejections.sql"
        with open(migration_path) as f:
            migration_sql = f.read()

        conn.execute(migration_sql)


def test_v8_creates_table_with_correct_structure(pg_conninfo: str) -> None:
    """V8 migration should create support_guardrail_rejections table with correct columns."""
    _apply_v8_migration(pg_conninfo)

    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Check table exists
        result = conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'support_guardrail_rejections')"
        ).fetchone()
        assert result[0] is True, "Table should exist"

        # Check column definitions
        columns = conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'support_guardrail_rejections' "
            "ORDER BY ordinal_position"
        ).fetchall()

        column_info = {row[0]: {"type": row[1], "nullable": row[2], "default": row[3]} for row in columns}

        # Validate id column (UUIDv7 PK)
        assert "id" in column_info
        assert column_info["id"]["type"] in ("uuid", "UUID")
        assert column_info["id"]["nullable"] == "NO"
        assert "uuid_generate_v7()" in column_info["id"]["default"]

        # Validate session_id column
        assert "session_id" in column_info
        assert column_info["session_id"]["type"] in ("uuid", "UUID")
        assert column_info["session_id"]["nullable"] == "NO"

        # Validate rejection_reason column with CHECK constraint
        assert "rejection_reason" in column_info
        assert column_info["rejection_reason"]["type"] in ("character varying", "VARCHAR")
        assert column_info["rejection_reason"]["nullable"] == "NO"

        # Validate message_hash column (SHA-256 hex)
        assert "message_hash" in column_info
        assert column_info["message_hash"]["type"] in ("character", "CHAR")
        assert column_info["message_hash"]["nullable"] == "NO"

        # Validate created_at column
        assert "created_at" in column_info
        assert column_info["created_at"]["type"] in ("timestamp with time zone", "TIMESTAMPTZ")
        assert column_info["created_at"]["nullable"] == "NO"


def test_v8_enforces_rejection_reason_check_constraint(pg_conninfo: str) -> None:
    """V8 migration should enforce CHECK constraint on rejection_reason."""
    _apply_v8_migration(pg_conninfo)

    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Should succeed with valid rejection_reason values
        valid_reasons = ["TOO_LONG", "PROMPT_INJECTION", "OFF_TOPIC"]
        for reason in valid_reasons:
            conn.execute(
                "INSERT INTO support_guardrail_rejections "
                "(session_id, rejection_reason, message_hash) "
                "VALUES (gen_random_uuid(), %s, 'a' || repeat('0', 63))",
                (reason,),
            )

        # Should fail with invalid rejection_reason
        with pytest.raises(Exception, match="CheckViolation"):  # psycopg.errors.CheckViolation
            conn.execute(
                "INSERT INTO support_guardrail_rejections "
                "(session_id, rejection_reason, message_hash) "
                "VALUES (gen_random_uuid(), 'INVALID_REASON', 'a' || repeat('0', 63))"
            )


def test_v8_creates_indexes_on_session_id_and_created_at(pg_conninfo: str) -> None:
    """V8 migration should create indexes on session_id and created_at DESC."""
    _apply_v8_migration(pg_conninfo)

    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Check indexes exist
        indexes = conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'support_guardrail_rejections'"
        ).fetchall()

        index_names = [row[0] for row in indexes]

        # Validate session_id index
        assert "idx_sgr_session_id" in index_names

        # Validate created_at index (DESC order)
        assert "idx_sgr_created_at" in index_names
        created_at_index_def = next(row[1] for row in indexes if row[0] == "idx_sgr_created_at")
        assert "DESC" in created_at_index_def.upper()


def test_v8_no_modified_at_column_append_only(pg_conninfo: str) -> None:
    """V8 migration should NOT have modified_at column (append-only log table)."""
    _apply_v8_migration(pg_conninfo)

    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Check that modified_at column does NOT exist
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'support_guardrail_rejections' AND column_name = 'modified_at'"
        ).fetchall()

        assert len(columns) == 0, "modified_at column should NOT exist (append-only table)"
