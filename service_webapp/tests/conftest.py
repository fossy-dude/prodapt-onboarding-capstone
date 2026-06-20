"""Shared pytest fixtures for the service_webapp test suite (Story 1.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
