"""FastAPI application entrypoint for ``service_webapp`` (Story 1.4).

Wires the config singleton (fail-fast at boot), the OTEL trace middleware and the
health router onto a single FastAPI app. Adapter lifecycle (Postgres pool, Valkey
client) is managed via the ASGI lifespan so ``/ready`` can probe them. Served on
port 8000 — ``curl http://localhost:8000/health`` (architecture §1.15.1).
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from adapters.cognito import CognitoProvider, MinistackCognitoProvider
from adapters.milvus import MilvusAdapter
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
    account_router,
    auth_router,
    router as subscriber_router,
)
from routers.balance import router as balance_router
from routers.health import router as health_router
from routers.simulator import (
    connection_manager as _trace_connection_manager,
    notification_connection_manager as _notification_connection_manager,
    router as simulator_router,
    to_notification_broadcast,
    ws_router as simulator_ws_router,
)
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
    from core.protocols.vector_store import VectorStoreProtocol


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
    if getattr(app.state, "milvus_adapter", None) is None:
        try:
            _milvus = MilvusAdapter(settings.milvus_db_uri)
            await _milvus.create_collections_if_absent()
            app.state.milvus_adapter = _milvus
            owned.append("milvus_adapter")
        except Exception as exc:
            logging.getLogger(__name__).warning("Milvus Lite unavailable at startup: %s", exc)
            app.state.milvus_adapter = None
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
    if getattr(app.state, "kafka_producer", None) is None:
        brokers = [b.strip() for b in settings.kafka_brokers.split(",")]
        _producer = AIOKafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v).encode(),
        )
        await _producer.start()
        app.state.kafka_producer = _producer
        owned.append("kafka_producer")

    trace_consumer_task: asyncio.Task | None = None
    if getattr(app.state, "trace_consumer", None) is None:
        brokers = [b.strip() for b in settings.kafka_brokers.split(",")]
        _consumer = AIOKafkaConsumer(
            "simulator.trace",
            bootstrap_servers=brokers,
            group_id="simulator-trace-broadcaster",
            auto_offset_reset="latest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        app.state.trace_consumer = _consumer
        owned.append("trace_consumer")

        async def _broadcast_trace_events() -> None:
            try:
                await _consumer.start()
                async for msg in _consumer:
                    try:
                        if msg.value is None:
                            continue
                        await _trace_connection_manager.broadcast(msg.value)
                    except Exception as exc:
                        logging.getLogger(__name__).debug("trace broadcast error: %s", exc)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logging.getLogger(__name__).warning("trace consumer error: %s", exc)
            finally:
                try:
                    await _consumer.stop()
                except Exception:
                    pass

        trace_consumer_task = asyncio.create_task(_broadcast_trace_events())

    notification_consumer_task: asyncio.Task | None = None
    if getattr(app.state, "notification_consumer", None) is None:
        brokers = [b.strip() for b in settings.kafka_brokers.split(",")]
        _nconsumer = AIOKafkaConsumer(
            "notification.events",
            bootstrap_servers=brokers,
            group_id="notification-portal-broadcaster",
            auto_offset_reset="latest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        app.state.notification_consumer = _nconsumer
        owned.append("notification_consumer")

        async def _broadcast_notification_events() -> None:
            try:
                await _nconsumer.start()
                async for msg in _nconsumer:
                    try:
                        await _notification_connection_manager.broadcast(to_notification_broadcast(msg.value))
                    except Exception as exc:
                        logging.getLogger(__name__).debug("notification broadcast error: %s", exc)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logging.getLogger(__name__).warning("notification consumer error: %s", exc)
            finally:
                try:
                    await _nconsumer.stop()
                except Exception:
                    pass

        notification_consumer_task = asyncio.create_task(_broadcast_notification_events())

    try:
        yield
    finally:
        if notification_consumer_task is not None:
            notification_consumer_task.cancel()
            try:
                await notification_consumer_task
            except asyncio.CancelledError:
                pass
        if trace_consumer_task is not None:
            trace_consumer_task.cancel()
            try:
                await trace_consumer_task
            except asyncio.CancelledError:
                pass
        if "kafka_producer" in owned:
            await app.state.kafka_producer.stop()
        if "db_adapter" in owned:
            await app.state.db_adapter.close()
        if "cache_adapter" in owned:
            await app.state.cache_adapter.close()
        if "milvus_adapter" in owned:
            await app.state.milvus_adapter.close()


def create_app(
    *,
    db_adapter: DatabaseProtocol | None = None,
    cache_adapter: CacheProtocol | None = None,
    milvus_adapter: VectorStoreProtocol | None = None,
    cognito_provider: CognitoProvider | None = None,
    registration_service: RegistrationService | RegistrationRepository | None = None,
    jwt_validator: JWTValidator | None = None,
    step_up_service: StepUpOtpService | None = None,
    kafka_producer: object | None = None,
    trace_consumer: object | None = None,
    notification_consumer: object | None = None,
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
    app.include_router(subscriber_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(balance_router)
    app.include_router(simulator_router)
    app.include_router(simulator_ws_router)
    app.state.db_adapter = db_adapter
    app.state.cache_adapter = cache_adapter
    app.state.milvus_adapter = milvus_adapter
    app.state.cognito_provider = cognito_provider
    app.state.registration_service = registration_service
    app.state.jwt_validator = jwt_validator
    app.state.step_up_service = step_up_service
    app.state.kafka_producer = kafka_producer
    app.state.trace_consumer = trace_consumer
    app.state.notification_consumer = notification_consumer
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
