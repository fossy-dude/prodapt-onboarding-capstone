"""Integration test: POST /simulator/activate end-to-end (Story 2.9, AC #1, #2, #3).

Uses testcontainers Postgres (project image with pg_uuidv7) + Redpanda. Seeds a
plan + subscriber + registration + NEW_ACTIVATION order, then drives the real
endpoint (real db adapter + real Kafka producer) and asserts:
  - the order is transitioned to ACTIVATED in Postgres (AC #1)
  - billing_wallet_balances is seeded with balance_paise = plan price (AC #2)
  - a notification.events event reaches Kafka with the correct envelope (AC #3)
  - the broadcast helper masks MSISDN before it reaches a WS client (AC #4)

Valkey is faked (FakeCache records set_balance); the no-TTL counter seed path is
unit-tested separately. The Notification Portal broadcaster is exercised via the
shared ``to_notification_broadcast`` helper + ``notification_connection_manager``
(mirrors the Story 2.8 trace-WS integration note: the lifespan consumer chain is
not stood up here).

Marked ``slow`` + ``integration``: requires a container runtime (Podman/Docker).
Skipped by default; run with ``pytest --run-slow`` or ``--run-integration``.
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid

import psycopg
import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from httpx import ASGITransport, AsyncClient
from testcontainers.core.generic import DockerContainer
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
_PG_IMAGE = "localhost/docker_postgres:latest"
REDPANDA_IMAGE = os.getenv("REDPANDA_IMAGE", "redpandadata/redpanda:v23.3.21")
_PRICE_PAISE = 4999


class _FakeCache:
    """Records the Valkey balance seed (CacheProtocol subset)."""

    def __init__(self) -> None:
        self.seeds: list[tuple[str, int]] = []

    async def set_balance(self, msisdn: str, paise: int) -> None:
        self.seeds.append((msisdn, paise))

    async def ping(self) -> bool:
        return True


@pytest.fixture(scope="module")
def redpanda() -> str:
    """Start a Redpanda container exposing the Kafka-compatible port 9092."""
    container = DockerContainer(REDPANDA_IMAGE).with_command(
        "redpanda start --overprovisioned --smp 1 --memory 256M "
        "--reserve-memory 0M --node-id 0 --check=false "
        "--kafka-addr 0.0.0.0:9092 --advertise-kafka-addr 127.0.0.1:{port}"
    )
    container.with_exposed_ports(9092)
    with container as c:
        import socket
        import time

        port = int(c.get_exposed_port(9092))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        yield f"127.0.0.1:{port}"


@pytest.fixture
async def seeded_db(redpanda: str):
    """Start Postgres, apply migrations, seed a plan + subscriber + registration + order.

    Returns (conninfo, registration_id, msisdn, plan_id, subscriber_id, order_id).
    """
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

            msisdn = "9876543210"
            plan_id = uuid.uuid4()
            subscriber_id = uuid.uuid4()
            order_id = uuid.uuid4()
            registration_id = f"REG-20260623-{uuid.uuid4().hex[:8]}"

            await conn.execute(
                """INSERT INTO plans_plans (id, plan_name, plan_code, price_paise, validity_days)
                   VALUES (%s, %s, %s, %s, %s)""",
                (plan_id, "Integration Plan", "INTPLAN", _PRICE_PAISE, 28),
            )
            await conn.execute(
                """INSERT INTO identity_subscribers (id, msisdn, subscriber_name, plan_id)
                   VALUES (%s, %s, %s, %s)""",
                (subscriber_id, msisdn, "Integration User", plan_id),
            )
            await conn.execute(
                """INSERT INTO identity_registrations
                   (id, subscriber_id, registration_type, registration_id, status)
                   VALUES (%s, %s, %s, %s, %s)""",
                (uuid.uuid4(), subscriber_id, "NEW_ACTIVATION", registration_id, "REGISTRATION_COMPLETE"),
            )
            await conn.execute(
                """INSERT INTO ops_order_fulfilment (id, subscriber_id, plan_id, fulfilment_status, fulfilment_type)
                   VALUES (%s, %s, %s, %s, %s)""",
                (order_id, subscriber_id, plan_id, "KYC_VERIFIED", "NEW_ACTIVATION"),
            )
        yield {
            "conninfo": conninfo,
            "registration_id": registration_id,
            "msisdn": msisdn,
            "plan_id": plan_id,
            "subscriber_id": subscriber_id,
            "order_id": order_id,
        }


@pytest.mark.asyncio
async def test_activate_transitions_order_and_seeds_wallet(seeded_db, redpanda: str) -> None:
    """POST /activate drives the order to ACTIVATED + seeds the wallet (AC #1, #2)."""
    from unittest.mock import MagicMock

    from adapters.postgres import Psycopg3AsyncAdapter
    from core.auth import FakeJWTValidator
    from main import create_app

    db = Psycopg3AsyncAdapter(seeded_db["conninfo"])
    producer = AIOKafkaProducer(
        bootstrap_servers=redpanda,
        value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v).encode(),
    )
    await producer.start()
    cache = _FakeCache()
    app = create_app(
        jwt_validator=FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["dev"]}),
        db_adapter=db,
        cache_adapter=cache,
        kafka_producer=producer,
        trace_consumer=MagicMock(),
        notification_consumer=MagicMock(),
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/simulator/activate",
                json={"lookup_type": "registration_id", "lookup_value": seeded_db["registration_id"]},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["status"] == "ACTIVATED"
        assert data["msisdn"] == seeded_db["msisdn"]
        assert data["balance_paise"] == _PRICE_PAISE

        # DB assertions (AC #1, #2)
        async with await psycopg.AsyncConnection.connect(seeded_db["conninfo"]) as conn:
            cur = await conn.execute(
                "SELECT fulfilment_status, completed_at FROM ops_order_fulfilment WHERE id = %s",
                (seeded_db["order_id"],),
            )
            order_row = await cur.fetchone()
            assert order_row[0] == "ACTIVATED"
            assert order_row[1] is not None
            cur = await conn.execute(
                "SELECT balance_paise FROM billing_wallet_balances WHERE subscriber_id = %s",
                (seeded_db["subscriber_id"],),
            )
            wallet_row = await cur.fetchone()
            assert wallet_row[0] == _PRICE_PAISE

        # Valkey seed captured by the fake cache (AC #2)
        assert cache.seeds == [(seeded_db["msisdn"], _PRICE_PAISE)]
    finally:
        await producer.stop()
        await db.close()


@pytest.mark.asyncio
async def test_activate_publishes_notification_event(seeded_db, redpanda: str) -> None:
    """POST /activate publishes a notification.events event readable from Kafka (AC #3)."""
    from unittest.mock import MagicMock

    from adapters.postgres import Psycopg3AsyncAdapter
    from core.auth import FakeJWTValidator
    from main import create_app

    db = Psycopg3AsyncAdapter(seeded_db["conninfo"])
    producer = AIOKafkaProducer(
        bootstrap_servers=redpanda,
        value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v).encode(),
    )
    await producer.start()
    app = create_app(
        jwt_validator=FakeJWTValidator({"sub": str(uuid.uuid4()), "cognito:groups": ["dev"]}),
        db_adapter=db,
        cache_adapter=_FakeCache(),
        kafka_producer=producer,
        trace_consumer=MagicMock(),
        notification_consumer=MagicMock(),
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/simulator/activate",
                json={"lookup_type": "registration_id", "lookup_value": seeded_db["registration_id"]},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert r.status_code == 200, r.text
        trace_id = r.json()["meta"]["trace_id"]

        consumer = AIOKafkaConsumer(
            "notification.events",
            bootstrap_servers=redpanda,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode()),
            consumer_timeout_ms=15_000,
        )
        await consumer.start()
        try:
            found = False
            async for msg in consumer:
                value = msg.value
                if value.get("trace_id") == trace_id:
                    found = True
                    assert value["event_type"] == "notification.events"
                    assert value["payload"]["notification_type"] == "SIM_ACTIVATION"
                    assert value["payload"]["msisdn"] == seeded_db["msisdn"]
                    assert msg.key is not None and msg.key.decode() == seeded_db["msisdn"]
                    break
            assert found, "activation notification not found on notification.events"
        finally:
            await consumer.stop()
    finally:
        await producer.stop()
        await db.close()


@pytest.mark.asyncio
async def test_activate_notification_masks_msisdn_for_ws_client(seeded_db, redpanda: str) -> None:
    """The notification broadcast masks the MSISDN before it reaches a WS client (AC #4)."""
    from unittest.mock import AsyncMock

    from routers.simulator import notification_connection_manager, to_notification_broadcast

    # The activation publishes the full MSISDN into the envelope payload; the
    # broadcaster helper masks it to [-4:] (*** prefix) before fan-out.
    ws = AsyncMock()
    await notification_connection_manager.connect(ws)
    try:
        envelope = {
            "event_type": "notification.events",
            "trace_id": "a" * 32,
            "payload": {"msisdn": seeded_db["msisdn"], "notification_type": "SIM_ACTIVATION"},
        }
        msg = to_notification_broadcast(envelope)
        await notification_connection_manager.broadcast(msg)
        ws.send_json.assert_awaited_once_with(msg)
        assert seeded_db["msisdn"] not in json.dumps(msg)
    finally:
        notification_connection_manager.disconnect(ws)
