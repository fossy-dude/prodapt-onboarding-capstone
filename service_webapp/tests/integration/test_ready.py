"""Integration test: ``/ready`` returns 200 when Postgres + Valkey are healthy (AC #4).

Uses testcontainers (architecture §1.11.8 — do NOT mock the dependencies). Marked
``slow`` + ``integration``: it needs a container runtime (Docker/Podman socket)
and is therefore skipped by the default ``just test`` gate (``-m "not slow"``).
Run explicitly with ``pytest -m slow`` when a container runtime is available.
"""

from __future__ import annotations

import socket
import time

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.core.generic import DockerContainer
from testcontainers.postgres import PostgresContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]


@pytest.fixture(scope="module")
def postgres() -> PostgresContainer:
    """Real Postgres container for the readiness ping (waits until it accepts connections)."""
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="module")
def valkey() -> DockerContainer:
    """Real Valkey container (redis protocol) for the readiness ping."""
    container = DockerContainer("valkey/valkey:7.2").with_exposed_ports(6379)
    container.start()
    host_port = int(container.get_exposed_port(6379))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", host_port), timeout=1):
                break
        except OSError:
            time.sleep(0.3)
    else:
        container.stop()
        pytest.fail("valkey container did not become ready")
    try:
        yield container
    finally:
        container.stop()


async def test_ready_returns_200_when_deps_healthy(postgres: PostgresContainer, valkey: DockerContainer) -> None:
    """Both deps healthy → ``/ready`` 200 (AC #4)."""
    from adapters.postgres import Psycopg3AsyncAdapter
    from adapters.redis import ValkeyAdapter
    from main import create_app

    conninfo = (
        f"host=127.0.0.1 port={postgres.get_exposed_port(5432)} dbname={postgres.dbname} "
        f"user={postgres.username} password={postgres.password} connect_timeout=2"
    )
    cache_url = f"redis://127.0.0.1:{valkey.get_exposed_port(6379)}/0"

    db_adapter = Psycopg3AsyncAdapter(conninfo)
    cache_adapter = ValkeyAdapter(cache_url)
    app = create_app(db_adapter=db_adapter, cache_adapter=cache_adapter)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ready")

    assert resp.status_code == 200
    assert resp.json()["detail"] == {"postgres": True, "valkey": True}
