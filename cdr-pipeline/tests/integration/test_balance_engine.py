r"""Integration test: balance engine warm-up → deduct → flush (Story 2.3, Task 7).

Slow / integration: needs a container runtime (Podman/Docker socket) and uses
testcontainers Postgres + Valkey — the REAL database + cache, NOT mocks. Skipped by
the default ``just test-cdr`` gate (``-m "not slow"``). Run with rootless Podman:

    DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
        cd cdr-pipeline && uvx --with tox-uv tox -e test -- -m slow
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from adapters.postgres import Psycopg3AsyncAdapter, conninfo_from
from adapters.redis import ValkeyAdapter
from consumer.balance_writer import BalanceEngine
from consumer.startup import load_balances_from_postgres
from core.config import DatabaseSettings
from models.cdr import SmsCdr

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[3] / "service_webapp" / "db" / "migrations"
_IMAGE = "localhost/docker_postgres:latest"  # Story 1.2 custom image with pg_uuidv7

_SUBSCRIBER = UUID("0192a4d0-1234-7000-8000-000000000abc")
_SUBSCRIBER2 = UUID("0192a4d0-9999-7000-8000-000000000def")
_MSISDN = "9876543210"
_MSISDN2 = "9876543211"
_TRACE = "0123456789abcdef0123456789abcdef"


@pytest.fixture
async def postgres():
    """PostgresContainer with V1+V2 schema applied."""
    import psycopg  # noqa: F401 (imported only by slow tests)

    with PostgresContainer(_IMAGE) as pg:
        conninfo = (
            f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} "
            f"user={pg.username} password={pg.password}"
        )
        # Extensions + baseline migrations (the image only ships pg_uuidv7 binary).
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            for ext in ("pg_uuidv7", "pgcrypto", "pg_trgm", "btree_gin"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            for name in ("V1__baseline_schema.sql", "V2__modified_at_trigger.sql"):
                await conn.execute((_MIGRATIONS / name).read_text())
        yield conninfo


@pytest.fixture
def valkey():
    """Valkey (RedisContainer)."""
    with RedisContainer(image="docker.io/valkey/valkey:8-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}"


async def test_warmup_seeds_balances_and_builds_indices(postgres: str, valkey: str):
    """Warm-up seeds balance:{msisdn} keys and builds subscriber→msisdn index (Task 7)."""
    db = Psycopg3AsyncAdapter(postgres)
    cache = ValkeyAdapter(valkey)

    try:
        # Seed billing_wallet_balances
        async with db.transaction() as conn:
            # Insert subscriber records
            await conn.execute(
                "INSERT INTO identity_subscribers (id, msisdn, subscriber_name) VALUES "
                "($1, $2, 'Test One'), ($3, $4, 'Test Two')",
                _SUBSCRIBER,
                _MSISDN,
                _SUBSCRIBER2,
                _MSISDN2,
            )
            # Insert wallet balances
            await conn.execute(
                "INSERT INTO billing_wallet_balances (subscriber_id, msisdn, balance_paise) VALUES "
                "($1, $2, 100000), ($3, $4, 50000)",
                _SUBSCRIBER,
                _MSISDN,
                _SUBSCRIBER2,
                _MSISDN2,
            )

        # Run warm-up
        state = await load_balances_from_postgres(db, cache)

        # Assert warm-up seeded Valkey keys
        balance1 = await cache.get_str(f"balance:{_MSISDN}")
        assert balance1 == "100000"

        balance2 = await cache.get_str(f"balance:{_MSISDN2}")
        assert balance2 == "50000"

        # Assert indices built
        assert state.subscriber_to_msisdn[str(_SUBSCRIBER)] == _MSISDN
        assert state.msisdn_to_subscriber[_MSISDN] == str(_SUBSCRIBER)
        assert state.count == 2

    finally:
        await db.close()
        await cache.close()


async def test_deduct_flush_updates_postgres_balance_and_ledger(postgres: str, valkey: str):
    """Deduct → flush updates Postgres balance_paise and inserts ledger row (Task 7)."""
    db = Psycopg3AsyncAdapter(postgres)
    cache = ValkeyAdapter(valkey)

    try:
        # Seed subscriber + wallet
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO identity_subscribers (id, msisdn, subscriber_name) VALUES ($1, $2, 'Test')",
                _SUBSCRIBER,
                _MSISDN,
            )
            await conn.execute(
                "INSERT INTO billing_wallet_balances (subscriber_id, msisdn, balance_paise) VALUES ($1, $2, 100000)",
                _SUBSCRIBER,
                _MSISDN,
            )

        # Warm-up
        engine = BalanceEngine(cache, db, flush_interval=0.5, flush_dirty_threshold=10)
        await engine.warmup()

        # Build CDR
        cdr = SmsCdr(
            cdr_id=UUID("0192a4d0-0001-7000-8000-000000000001"),
            session_id=UUID("0192a4d0-abcd-7000-8000-000000000001"),
            subscriber_id=_SUBSCRIBER,
            telecom_circle="KA",
            cost_paise=250,
            start_time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            message_direction="MT",
            sms_status="delivered",
        )

        # Deduct
        await engine.deduct(cdr)

        # Assert Valkey balance updated
        balance_after = await cache.get_str(f"balance:{_MSISDN}")
        assert int(balance_after) == 99750  # 100000 - 250

        # Flush
        await engine._flush()

        # Assert Postgres wallet balance updated
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT balance_paise FROM billing_wallet_balances WHERE msisdn = $1",
                _MSISDN,
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 99750

        # Assert billing_transactions ledger row exists
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT amount_paise, balance_before_paise, balance_after_paise, reference_id "
                "FROM billing_transactions WHERE reference_id = $1",
                cdr.cdr_id,
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == -250  # amount_paise (negative for deduction)
        assert row[1] == 100000  # balance_before
        assert row[2] == 99750  # balance_after

        # Assert Valkey key still exists (not deleted)
        balance_final = await cache.get_str(f"balance:{_MSISDN}")
        assert balance_final == "99750"

    finally:
        await engine.stop()
        await db.close()
        await cache.close()
