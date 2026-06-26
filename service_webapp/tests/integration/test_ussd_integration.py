"""Integration tests for USSD session handler (Story 4.4).

Testcontainers: Postgres (project image) + Valkey.
Tests the full session flow: root → balance → back → recharge_select → confirm → result.

Marked ``slow``: requires a container runtime (Podman/Docker).
Skipped by default; run with ``pytest --run-slow``.
"""

from __future__ import annotations

import pathlib
import socket
import time
import uuid

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
_PG_IMAGE = "localhost/docker_postgres:latest"
_MSISDN = "919000000001"
_SESSION_ID = "ussd-integ-sess-001"


@pytest.fixture(scope="module")
def valkey_container():
    from testcontainers.core.generic import DockerContainer

    container = DockerContainer("valkey/valkey:7.2")
    container.with_exposed_ports(6379)
    with container as c:
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
async def seeded_env(valkey_container: str):
    """Postgres + Valkey with subscriber, plan, subscription, payment method seeded."""
    from testcontainers.postgres import PostgresContainer

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
                "V6__recharge_failure_reason.sql",
            ):
                await conn.execute((_MIGRATIONS / name).read_text())

            plan_id = uuid.uuid4()
            subscriber_id = uuid.uuid4()
            pm_id = uuid.uuid4()

            await conn.execute(
                """INSERT INTO plans_plans
                   (id, plan_name, plan_code, price_paise, validity_days,
                    data_limit_mb, voice_minutes, sms_count)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (plan_id, "USSD Plan", "USSDPLAN", 19900, 28, 2048, 300, 50),
            )
            await conn.execute(
                """INSERT INTO identity_subscribers
                   (id, msisdn, subscriber_name, status)
                   VALUES (%s, %s, %s, 'active')""",
                (subscriber_id, _MSISDN, "Test Subscriber"),
            )
            await conn.execute(
                """INSERT INTO plans_subscriptions
                   (id, subscriber_id, plan_id, start_date, end_date, status)
                   VALUES (gen_random_uuid(), %s, %s, NOW(), NOW() + interval '28 days', 'active')""",
                (subscriber_id, plan_id),
            )
            await conn.execute(
                """INSERT INTO billing_wallet_balances
                   (subscriber_id, msisdn, balance_paise)
                   VALUES (%s, %s, 50000)""",
                (subscriber_id, _MSISDN),
            )
            await conn.execute(
                """INSERT INTO recharge_payment_methods
                   (id, subscriber_id, method_type, token, last_four, is_active)
                   VALUES (%s, %s, 'card', 'tok_test_1234', '1234', TRUE)""",
                (pm_id, subscriber_id),
            )

        yield {
            "conninfo": conninfo,
            "valkey_url": valkey_container,
            "subscriber_id": str(subscriber_id),
            "plan_id": str(plan_id),
            "pm_id": str(pm_id),
        }


@pytest.mark.asyncio
async def test_full_ussd_session_flow(seeded_env):
    """Full session flow: root → balance → back → recharge_select → confirm → result."""
    from adapters.postgres import Psycopg3AsyncAdapter
    from adapters.redis import ValkeyAdapter
    from core.auth import FakeJWTValidator
    from main import create_app

    db = Psycopg3AsyncAdapter(seeded_env["conninfo"])
    cache = ValkeyAdapter(seeded_env["valkey_url"])

    # Seed balance in Valkey
    await cache.set_balance(_MSISDN, 50000)

    app = create_app(
        db_adapter=db,
        cache_adapter=cache,
        jwt_validator=FakeJWTValidator(payload={"sub": seeded_env["subscriber_id"], "cognito:groups": ["subscriber"]}),
    )

    def req(button: str = "", session_id: str = _SESSION_ID) -> dict:
        return {
            "msisdn": _MSISDN,
            "session_id": session_id,
            "button_pressed": button,
            "ussd_string": "",
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: new session → root menu
        r = await client.post("/api/v1/ussd/callback", json=req())
        assert r.status_code == 200
        assert "Welcome" in r.text
        assert "text/plain" in r.headers["content-type"]

        # Step 2: button "1" → balance screen
        r = await client.post("/api/v1/ussd/callback", json=req(button="1"))
        assert r.status_code == 200
        assert "Rs.500.00" in r.text

        # Step 3: button "0" at balance → back to root
        r = await client.post("/api/v1/ussd/callback", json=req(button="0"))
        assert r.status_code == 200
        assert "Welcome" in r.text

        # Step 4: button "3" → recharge_select
        r = await client.post("/api/v1/ussd/callback", json=req(button="3"))
        assert r.status_code == 200
        assert "1." in r.text
        assert "USSD Plan" in r.text

        # Step 5: button "1" → recharge_confirm screen
        r = await client.post("/api/v1/ussd/callback", json=req(button="1"))
        assert r.status_code == 200
        assert "Rs." in r.text
        assert "Press 1 to confirm" in r.text

        # Step 6: confirm recharge
        r = await client.post("/api/v1/ussd/callback", json=req(button="1"))
        assert r.status_code == 200
        assert "Recharge successful" in r.text

    await cache.close()
    await db.close()
