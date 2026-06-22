"""FastAPI application entrypoint for ``service_webapp`` (Story 1.4).

Wires the config singleton (fail-fast at boot), the OTEL trace middleware and the
health router onto a single FastAPI app. Adapter lifecycle (Postgres pool, Valkey
client) is managed via the ASGI lifespan so ``/ready`` can probe them. Served on
port 8000 — ``curl http://localhost:8000/health`` (architecture §1.15.1).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from adapters.cognito import CognitoProvider, MinistackCognitoProvider
from adapters.postgres import Psycopg3AsyncAdapter, conninfo_from
from adapters.redis import ValkeyAdapter

# Importing settings eager-loads + validates config at boot (fail-fast, AC #1); it is
# also consumed in the lifespan below, so the import is not merely a side effect.
from core.auth import JWTValidator, _cognito_jwks_url
from core.config import settings
from core.errors import register_exception_handlers
from core.middleware import OtelTraceMiddleware
from core.step_up import StepUpOtpService
from routers.account import (
    auth_router,
    router as account_router,
)
from routers.health import router as health_router
from services.registration import (
    PostgresRegistrationRepository,
    RegistrationRepository,
    RegistrationService,
)

if TYPE_CHECKING:
    # Type-only symbols: referenced only in annotations (runtime uses the concrete adapters).
    from collections.abc import AsyncIterator

    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol


def _setup_tracer() -> None:
    """Install a real ``TracerProvider`` so fresh root spans get real trace ids.

    Idempotent across repeated app construction (tests create the app many times):
    OTel raises if a provider is already set, which we treat as a no-op.
    """
    try:
        trace.set_tracer_provider(TracerProvider())
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create adapters on startup (unless injected) and close them on shutdown.

    Only adapters created here are closed on shutdown; injected adapters (e.g.
    from tests) are left for the caller to manage so lifespan never destroys
    externally-owned resources.
    """
    owned: list[str] = []
    if getattr(app.state, "db_adapter", None) is None:
        app.state.db_adapter = Psycopg3AsyncAdapter(conninfo_from(settings.db))
        owned.append("db_adapter")
    if getattr(app.state, "cache_adapter", None) is None:
        app.state.cache_adapter = ValkeyAdapter(settings.valkey_url)
        owned.append("cache_adapter")
    if getattr(app.state, "cognito_provider", None) is None:
        app.state.cognito_provider = MinistackCognitoProvider(settings)
    # The registration service composes the DB repository + Cognito provider; build
    # it only when not injected (tests inject a service wired to fakes).
    if getattr(app.state, "registration_service", None) is None:
        repo = PostgresRegistrationRepository(app.state.db_adapter)
        app.state.registration_service = RegistrationService(repo, app.state.cognito_provider)
    if getattr(app.state, "jwt_validator", None) is None:
        app.state.jwt_validator = JWTValidator(_cognito_jwks_url(settings))
    if getattr(app.state, "step_up_service", None) is None:
        app.state.step_up_service = StepUpOtpService(app.state.cache_adapter, settings.otp_step_up_ttl_seconds)
    try:
        yield
    finally:
        if "db_adapter" in owned:
            await app.state.db_adapter.close()
        if "cache_adapter" in owned:
            await app.state.cache_adapter.close()


def create_app(
    *,
    db_adapter: DatabaseProtocol | None = None,
    cache_adapter: CacheProtocol | None = None,
    cognito_provider: CognitoProvider | None = None,
    registration_service: RegistrationService | RegistrationRepository | None = None,
    jwt_validator: JWTValidator | None = None,
    step_up_service: StepUpOtpService | None = None,
) -> FastAPI:
    """Construct the FastAPI app.

    Adapters/services may be injected (primarily for tests); when omitted they are
    created from ``settings`` during the ASGI lifespan.
    """
    _setup_tracer()
    app = FastAPI(title="SBOAI Capstone", version="0.1.0", lifespan=lifespan)
    app.add_middleware(OtelTraceMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(account_router)
    app.include_router(auth_router)
    app.state.db_adapter = db_adapter
    app.state.cache_adapter = cache_adapter
    app.state.cognito_provider = cognito_provider
    app.state.registration_service = registration_service
    app.state.jwt_validator = jwt_validator
    app.state.step_up_service = step_up_service
    return app


# Module-level app object — what ``uvicorn src.main:app`` imports.
app = create_app()


def main() -> None:
    """Run the app with uvicorn on port 8000 (matches the README verify step).

    The string ``"main:app"`` (not ``"src.main:app"``) is correct when the app
    is launched with ``PYTHONPATH=src``, which puts ``src/`` on sys.path so the
    ``main`` module resolves to ``service_webapp/src/main.py``.
    """
    uvicorn.run("main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
