"""Integration test for guardrail rejection logging (Story 5.5 Task 6).

Tests that:
- log_rejection inserts correctly into support_guardrail_rejections table
- SHA-256 hash is computed and stored correctly (not raw message)
- Integration test with real Postgres + V1 + V8 migrations
"""

from __future__ import annotations

from pathlib import Path

import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "db" / "migrations"


@pytest.fixture(scope="module")
def pg() -> PostgresContainer:
    """Fresh Postgres container for integration testing."""
    with PostgresContainer("postgres:16") as container:
        yield container


@pytest.fixture(scope="module")
def pg_conninfo(pg: PostgresContainer) -> str:
    """Get connection string from test container."""
    return (
        f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} user={pg.username} password={pg.password}"
    )


def _apply_migrations(pg_conninfo: str) -> None:
    """Apply V1 and V8 migrations for testing."""
    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as conn:
        # Enable required extensions
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        # Create stub for uuid_generate_v7
        conn.execute(
            "CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid LANGUAGE sql AS $$ SELECT gen_random_uuid() $$"
        )

        # Apply V1 baseline (simplified - only support tables needed)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS support_chat_sessions (
                id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                msisdn VARCHAR(15),
                created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
            );
            """
        )

        # Apply V8 migration
        v8_path = MIGRATIONS_DIR / "V8__support_guardrail_rejections.sql"
        with open(v8_path) as f:
            conn.execute(f.read())


@pytest.mark.asyncio
async def test_log_rejection_integration(pg_conninfo: str) -> None:
    """Integration test: log_rejection inserts correctly into real Postgres."""
    import asyncio
    import hashlib

    import psycopg

    from agents.guardrails.validator import log_rejection

    _apply_migrations(pg_conninfo)

    # Create async database connection
    async with await psycopg.AsyncConnection.connect(pg_conninfo) as db:
        # Test data
        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "TOO_LONG"
        raw_message = "a" * 2001

        # Compute expected hash
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        # Call log_rejection
        await log_rejection(db, session_id, reason, raw_message)

        # Verify insertion
        async with db.cursor() as cursor:
            await cursor.execute("SELECT session_id, rejection_reason, message_hash FROM support_guardrail_rejections")
            rows = await cursor.fetchall()

        assert len(rows) == 1
        row_session_id, row_reason, row_hash = rows[0]

        # Verify session_id
        assert str(row_session_id) == session_id

        # Verify rejection_reason
        assert row_reason == reason

        # Verify SHA-256 hash (not raw message)
        assert row_hash == expected_hash
        assert len(row_hash) == 64  # SHA-256 hex is always 64 chars
        assert raw_message not in row_hash  # Raw message not stored


@pytest.mark.asyncio
async def test_log_rejection_all_reason_types(pg_conninfo: str) -> None:
    """Integration test: verify all three rejection reasons can be logged."""
    import uuid

    import psycopg

    from agents.guardrails.validator import log_rejection

    _apply_migrations(pg_conninfo)

    async with await psycopg.AsyncConnection.connect(pg_conninfo) as db:
        # Use unique session_id for this test to avoid conflicts
        session_id = str(uuid.uuid4())

        # Test all three rejection reasons
        for reason in ["TOO_LONG", "PROMPT_INJECTION", "OFF_TOPIC"]:
            raw_message = f"test message for {reason}"

            await log_rejection(db, session_id, reason, raw_message)

        # Verify all three rows were inserted for this session
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT rejection_reason FROM support_guardrail_rejections WHERE session_id = %s ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()

        assert len(rows) == 3
        reasons = [row[0] for row in rows]
        assert "TOO_LONG" in reasons
        assert "PROMPT_INJECTION" in reasons
        assert "OFF_TOPIC" in reasons


@pytest.mark.asyncio
async def test_log_rejection_unicode_message(pg_conninfo: str) -> None:
    """Integration test: verify Unicode messages are hashed correctly."""
    import hashlib
    import uuid

    import psycopg

    from agents.guardrails.validator import log_rejection

    _apply_migrations(pg_conninfo)

    async with await psycopg.AsyncConnection.connect(pg_conninfo) as db:
        # Use unique session_id for this test to avoid conflicts
        session_id = str(uuid.uuid4())
        reason = "OFF_TOPIC"
        raw_message = "我的余额是多少？ẞ"  # Chinese and German characters

        # Compute expected hash
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        await log_rejection(db, session_id, reason, raw_message)

        # Verify hash for this specific session
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT message_hash FROM support_guardrail_rejections WHERE session_id = %s",
                (session_id,),
            )
            rows = await cursor.fetchall()

        assert len(rows) == 1
        actual_hash = rows[0][0]

        assert actual_hash == expected_hash
        assert len(actual_hash) == 64


@pytest.mark.asyncio
async def test_log_rejection_pii_safety(pg_conninfo: str) -> None:
    """Integration test: verify PII is not stored (ARCH-32 compliance)."""
    import psycopg

    from agents.guardrails.validator import log_rejection

    _apply_migrations(pg_conninfo)

    async with await psycopg.AsyncConnection.connect(pg_conninfo) as db:
        # Use unique session_id for this test to avoid conflicts
        import uuid

        session_id = str(uuid.uuid4())
        reason = "PROMPT_INJECTION"

        # Test with potentially sensitive PII data
        raw_message = "my name is John Smith and my credit card is 4532-1234-5678-9010"

        await log_rejection(db, session_id, reason, raw_message)

        # Verify raw PII is NOT stored for this specific session
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT message_hash, rejection_reason FROM support_guardrail_rejections WHERE session_id = %s",
                (session_id,),
            )
            rows = await cursor.fetchall()

        assert len(rows) == 1
        message_hash = rows[0][0]

        # Verify raw PII is not in the hash
        assert "John Smith" not in message_hash
        assert "4532" not in message_hash
        assert "credit card" not in message_hash
