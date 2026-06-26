"""Integration test: V7 notification_threshold_config migration (AC #2, #5, #8).

Uses testcontainers to verify:
- notification_threshold_config table created with correct schema
- set_modified_at() trigger applied
- Seed data inserted correctly (low_balance_threshold_paise=1000, plan_expiry_reminder_days=3)
- Idempotent on re-run (ON CONFLICT DO NOTHING)

Marked ``slow`` + ``integration``: it needs a container runtime.
"""

from __future__ import annotations

import pathlib

import psycopg
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
_IMAGE = "localhost/docker_postgres:latest"


@pytest.fixture
async def db_conn() -> psycopg.AsyncConnection:
    """Postgres connection with extensions and V7 migration applied."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_IMAGE) as pg:
        conninfo = (
            f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} "
            f"user={pg.username} password={pg.password}"
        )

        # Create extensions required by migrations
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            for ext in ("pg_uuidv7", "pgcrypto", "pg_trgm", "btree_gin"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')

            # Apply V1 baseline schema (V7 depends on V2 trigger)
            v1_migration = (_MIGRATIONS / "V1__baseline_schema.sql").read_text()
            await conn.execute(v1_migration)

            # Apply V2 modified_at trigger (required by V7)
            v2_migration = (_MIGRATIONS / "V2__modified_at_trigger.sql").read_text()
            await conn.execute(v2_migration)

            # Apply V7 notification_threshold_config migration
            v7_migration = (_MIGRATIONS / "V7__notification_threshold_config.sql").read_text()
            await conn.execute(v7_migration)

        # Return a new connection for the test
        async with await psycopg.AsyncConnection.connect(conninfo) as conn:
            yield conn


async def test_notification_threshold_config_table_exists(db_conn: psycopg.AsyncConnection) -> None:
    """AC #2, #5, #8: Verify notification_threshold_config table created with correct schema."""
    cur = await db_conn.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'notification_threshold_config'
        ORDER BY ordinal_position;
    """)

    columns = {row[0]: {"type": row[1], "nullable": row[2], "default": row[3]} for row in await cur.fetchall()}

    # Verify all columns exist
    assert "id" in columns
    assert columns["id"]["type"] == "uuid"
    assert columns["id"]["nullable"] == "NO"

    assert "key" in columns
    assert columns["key"]["type"] == "character varying"
    assert columns["key"]["nullable"] == "NO"

    assert "value" in columns
    assert columns["value"]["type"] == "text"
    assert columns["value"]["nullable"] == "NO"

    assert "created_at" in columns
    assert columns["created_at"]["type"] == "timestamp with time zone"
    assert columns["created_at"]["nullable"] == "NO"

    assert "modified_at" in columns
    assert columns["modified_at"]["type"] == "timestamp with time zone"
    assert columns["modified_at"]["nullable"] == "NO"


async def test_notification_threshold_config_primary_key(db_conn: psycopg.AsyncConnection) -> None:
    """AC #8: Verify id column is PRIMARY KEY with UUID default."""
    cur = await db_conn.execute("""
        SELECT
            pg_attribute.attname AS column_name,
            pg_get_expr(pg_attrdef.adbin, pg_attrdef.adrelid) AS column_default
        FROM pg_index
        JOIN pg_attribute ON pg_attribute.attrelid = pg_index.indrelid
            AND pg_attribute.attnum = ANY(pg_index.indkey)
        LEFT JOIN pg_attrdef ON pg_attrdef.adrelid = pg_attribute.attrelid
            AND pg_attrdef.adnum = pg_attribute.attnum
        WHERE pg_index.indrelid = 'notification_threshold_config'::regclass
            AND pg_index.indisprimary;
    """)

    pk_info = await cur.fetchone()
    assert pk_info is not None
    assert pk_info[0] == "id"  # column_name
    assert "gen_random_uuid" in pk_info[1]  # column_default contains gen_random_uuid


async def test_notification_threshold_config_unique_key(db_conn: psycopg.AsyncConnection) -> None:
    """AC #8: Verify key column has UNIQUE constraint."""
    cur = await db_conn.execute("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'notification_threshold_config'::regclass
            AND contype = 'u'
            AND conname LIKE '%key%';
    """)

    unique_constraint = await cur.fetchone()
    assert unique_constraint is not None


async def test_notification_threshold_config_trigger_applied(db_conn: psycopg.AsyncConnection) -> None:
    """AC #8: Verify set_modified_at() trigger is applied."""
    cur = await db_conn.execute("""
        SELECT tgname
        FROM pg_trigger
        WHERE tgrelid = 'notification_threshold_config'::regclass
            AND tgname = 'trg_notification_threshold_config_modified_at';
    """)

    trigger = await cur.fetchone()
    assert trigger is not None
    assert trigger[0] == "trg_notification_threshold_config_modified_at"


async def test_notification_threshold_config_seed_data(db_conn: psycopg.AsyncConnection) -> None:
    """AC #2, #5: Verify seed data inserted correctly."""
    cur = await db_conn.execute("""
        SELECT key, value
        FROM notification_threshold_config
        ORDER BY key;
    """)

    rows = await cur.fetchall()
    assert len(rows) == 2

    # Convert to dict for easier assertion
    config = dict(rows)

    assert config["low_balance_threshold_paise"] == "1000"
    assert config["plan_expiry_reminder_days"] == "3"


async def test_notification_threshold_config_idempotent(db_conn: psycopg.AsyncConnection) -> None:
    """AC #8: Verify migration is idempotent (ON CONFLICT DO NOTHING)."""
    # Get initial count
    cur = await db_conn.execute("SELECT COUNT(*) FROM notification_threshold_config;")
    initial_count = (await cur.fetchone())[0]

    # Re-run the migration (simulate multiple runs)
    v7_migration = (_MIGRATIONS / "V7__notification_threshold_config.sql").read_text()
    await db_conn.execute(v7_migration)

    # Verify count unchanged
    cur = await db_conn.execute("SELECT COUNT(*) FROM notification_threshold_config;")
    final_count = (await cur.fetchone())[0]

    assert initial_count == final_count == 2


async def test_notification_threshold_config_modified_at_trigger_works(db_conn: psycopg.AsyncConnection) -> None:
    """AC #8: Verify modified_at trigger updates on UPDATE."""
    # Insert a test row and commit to start a new transaction
    async with db_conn.transaction():
        await db_conn.execute("""
            INSERT INTO notification_threshold_config (key, value)
            VALUES ('test_key', 'test_value');
        """)

    # Get created_at and modified_at in a new transaction
    async with db_conn.transaction():
        cur = await db_conn.execute("""
            SELECT created_at, modified_at
            FROM notification_threshold_config
            WHERE key = 'test_key';
        """)
        created_at, modified_at = await cur.fetchone()

    assert created_at == modified_at

    # Wait a bit (ensure timestamp difference)
    import asyncio

    await asyncio.sleep(0.01)

    # Update the row in a new transaction
    async with db_conn.transaction():
        await db_conn.execute("""
            UPDATE notification_threshold_config
            SET value = 'updated_value'
            WHERE key = 'test_key';
        """)

    # Check that modified_at changed in a new transaction
    async with db_conn.transaction():
        cur = await db_conn.execute("""
            SELECT created_at, modified_at
            FROM notification_threshold_config
            WHERE key = 'test_key';
        """)
        new_created_at, new_modified_at = await cur.fetchone()

    assert new_created_at == created_at  # created_at should not change
    assert new_modified_at > modified_at  # modified_at should be updated
