"""Integration test: balance endpoint reads real Valkey after INCRBY (Story 3.2, AC #2, #6).

Testcontainers: Postgres (project image) + Valkey. Seeds a plan + subscriber +
wallet row, then:
  1. Sets ``balance:{msisdn}`` via real ValkeyAdapter.set_balance.
  2. Calls GET /api/v1/subscriber/balance and asserts the Valkey value is returned.
  3. Calls INCRBY to simulate a CDR deduction, asserts updated balance returned.

Marked ``slow`` + ``integration``: requires a container runtime (Podman/Docker).
Skipped by default; run with ``pytest --run-slow`` or ``--run-integration``.
"""

from __future__ import annotations

import pathlib
import uuid

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
_PG_IMAGE = "localhost/docker_postgres:latest"
_PRICE_PAISE = 10000


@pytest.fixture(scope="module")
def valkey_container():
    """Start a Valkey (Redis-compatible) container."""
    from testcontainers.core.generic import DockerContainer

    container = DockerContainer("valkey/valkey:7.2")
    container.with_exposed_ports(6379)
    with container as c:
        import socket
        import time

        port = int(c.get_exposed_port(6379))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        yield f"redis://127.0.0.1:{port}"


@pytest.fixture(scope="module")
async def seeded_db_and_valkey(valkey_container: str):
    """Postgres + Valkey with a plan, subscriber, and wallet row seeded."""
    with PostgresContainer(_PG_IMAGE) as pg:
        conninfo = (
            f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} "
            f"user={pg.username} password={pg.password}"
        )
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            for ext in ("pg_uuidv7", "pgcrypto", "pg_trgm", "btree_gin"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            for name in (
                "V1__baseline_schema.sql",
                "V2__modified_at_trigger.sql",
                "V3__registration_extensions.sql",
                "V4__profile_address_columns.sql",
                "V5__append_only_grants.sql",
            ):
                await conn.execute((_MIGRATIONS / name).read_text())

            msisdn = "9988776655"
            plan_id = uuid.uuid4()
            subscriber_id = uuid.uuid4()

            await conn.execute(
                """INSERT INTO plans_plans (id, plan_name, plan_code, price_paise, validity_days,
                   data_limit_mb, voice_minutes, sms_count)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (plan_id, "Balance Test Plan", "BALTEST", _PRICE_PAISE, 28, 10240, 600, 100),
            )
            await conn.execute(
                """INSERT INTO identity_subscribers (id, msisdn, subscriber_name, plan_id)
                   VALUES (%s, %s, %s, %s)""",
                (subscriber_id, msisdn, "Balance Test User", plan_id),
            )
            await conn.execute(
                """INSERT INTO billing_wallet_balances
                   (subscriber_id, msisdn, balance_paise)
                   VALUES (%s, %s, %s)""",
                (subscriber_id, msisdn, _PRICE_PAISE),
            )

        yield {
            "conninfo": conninfo,
            "msisdn": msisdn,
            "subscriber_id": subscriber_id,
            "valkey_url": valkey_container,
        }


@pytest.mark.asyncio
async def test_balance_reads_valkey_after_seed(seeded_db_and_valkey) -> None:
    """AC #2, #6: real Valkey INCRBY → balance endpoint returns updated value."""
    import valkey.asyncio as avalkey

    from adapters.postgres import Psycopg3AsyncAdapter
    from adapters.redis import ValkeyAdapter
    from core.auth import FakeJWTValidator
    from main import create_app

    ctx = seeded_db_and_valkey
    msisdn = ctx["msisdn"]
    sub_id = str(ctx["subscriber_id"])

    db = Psycopg3AsyncAdapter(ctx["conninfo"])
    cache = ValkeyAdapter(ctx["valkey_url"])
    await cache.set_balance(msisdn, _PRICE_PAISE)

    app = create_app(
        jwt_validator=FakeJWTValidator({"sub": sub_id, "cognito:groups": ["subscriber"], "phone_number": msisdn}),
        db_adapter=db,
        cache_adapter=cache,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["balance_paise"] == _PRICE_PAISE

    raw_client = avalkey.from_url(ctx["valkey_url"])
    await raw_client.incrby(f"balance:{msisdn}", -500)
    await raw_client.aclose()

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r2 = await ac.get("/api/v1/subscriber/balance", headers={"Authorization": "Bearer tok"})
    assert r2.status_code == 200
    assert r2.json()["data"]["balance_paise"] == _PRICE_PAISE - 500

    await cache.close()
    await db.close()
