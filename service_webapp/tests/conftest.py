"""Shared pytest fixtures for the service_webapp test suite (Story 1.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def pytest_addoption(parser):
    """Register opt-in flags for integration / slow tests (skipped by default)."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests (skipped by default)",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="run slow tests (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip slow/integration tests unless an opt-in flag is given.

    Plain ``pytest`` runs unit tests only. Pass ``--run-integration`` and/or
    ``--run-slow`` to opt in. An item runs if ANY of its gate marks has its flag
    set, so tests marked both ``slow`` + ``integration`` (the integration suite)
    run under either flag. Mirrored in cdr-pipeline/tests/conftest.py.
    """
    run_integration = config.getoption("--run-integration")
    run_slow = config.getoption("--run-slow")
    if run_integration and run_slow:
        return  # both buckets opted in — nothing to gate
    skip_gate = pytest.mark.skip(reason="integration/slow test — rerun with --run-integration or --run-slow")
    for item in items:
        has_slow = "slow" in item.keywords
        has_integration = "integration" in item.keywords
        if (has_slow or has_integration) and not ((has_slow and run_slow) or (has_integration and run_integration)):
            item.add_marker(skip_gate)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Default app + async HTTP client.

    No adapters are injected and the ASGI lifespan is not exercised — use this for
    endpoints that touch no dependencies (``/health`` and the trace contract).
    """
    from main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
