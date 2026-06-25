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

# Story 5.10: Agent imports
from agents.conclusion import (
    create_conclusion_graph,
    get_conclusion_graph,
    set_conclusion_graph,
)
from agents.notification import (
    create_notification_graph,
    set_kafka_producer,
    set_notification_graph,
)

# Importing settings eager-loads + validates config at boot (fail-fast, AC #1); it is
# also consumed in the lifespan below, so the import is not merely a side effect.
from core.auth import JWTValidator, _cognito_jwks_url
from core.config import settings
from core.errors import register_exception_handlers
from core.middleware import OtelTraceMiddleware, SupportIdentityMiddleware
from core.rate_limit import RateLimitMiddleware
from core.step_up import StepUpOtpService

# Database commands/queries for notification dispatcher
from db.notifications.commands import insert_notification_event
from db.notifications.queries import get_preferences
from routers.account import (
    account_router,
    auth_router,
    router as subscriber_router,
)
from routers.balance import router as balance_router
from routers.chat import setup_copilotkit
from routers.health import router as health_router
from routers.notifications import router as notifications_router
from routers.recharge import router as recharge_router
from routers.simulator import (
    connection_manager as _trace_connection_manager,
    notification_connection_manager as _notification_connection_manager,
    router as simulator_router,
    to_notification_broadcast,
    ws_router as simulator_ws_router,
)
from routers.support import router as support_router
from routers.ussd import router as ussd_router
from services.notification_scheduler import run_plan_expiry_check
from services.registration import (
    PostgresRegistrationRepository,
    RegistrationRepository,
    RegistrationService,
)

# Optional apscheduler imports - may not be installed
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[misc]
    from apscheduler.triggers.cron import CronTrigger  # type: ignore[misc]
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]

# Data nudge consumer
from services.data_nudge_consumer import run_data_nudge_consumer

# Optional Azure OpenAI imports - may not be configured
try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None  # type: ignore[assignment]

from agents.conclusion.graph import set_conclusion_adapters
from agents.guardrails.validator import InputGuardrail
from agents.rag.retriever import HybridRetriever, set_retriever
from agents.support.graph import set_guardrail
from agents.support.tools import set_support_adapters
from core.observability.langfuse import get_langfuse_client

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
    # Re-bind the Support Agent tool singletons now that the real cache/DB adapters
    # exist (create_app wires them to the possibly-None app.state values at build
    # time; the lifespan owns the live instances). [Story 5.4]
    set_support_adapters(app.state.cache_adapter, app.state.db_adapter)
    # Story 5.10: Wire Conclusion Agent adapters
    set_conclusion_adapters(app.state.cache_adapter, app.state.db_adapter)

    # Story 5.10: Wire Conclusion and Notification Agents at startup
    if getattr(app.state, "conclusion_graph", None) is None:
        try:
            conclusion_graph = create_conclusion_graph()
            set_conclusion_graph(conclusion_graph)
            app.state.conclusion_graph = conclusion_graph
            owned.append("conclusion_graph")
            logging.getLogger(__name__).info("Conclusion Agent graph initialized")
        except Exception as exc:
            logging.getLogger(__name__).warning("Conclusion Agent init failed: %s", exc)
            app.state.conclusion_graph = None

    if getattr(app.state, "notification_graph", None) is None:
        try:
            notification_graph = create_notification_graph()
            set_notification_graph(notification_graph)
            app.state.notification_graph = notification_graph
            owned.append("notification_graph")
            logging.getLogger(__name__).info("Notification Agent graph initialized")
        except Exception as exc:
            logging.getLogger(__name__).warning("Notification Agent init failed: %s", exc)
            app.state.notification_graph = None

    # Wire Kafka producer to Notification Agent when available (set below)
    # The producer singleton is created later in the lifespan, so we'll wire it in
    # the kafka_producer initialization block
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
    # RAG retriever (Story 5.3): construct the AzureOpenAI client + HybridRetriever
    # and register the process-wide singleton so the ``rag_search`` LangGraph tool
    # callable resolves without DI closures. Azure/LangFuse are optional — missing
    # config (empty key) degrades gracefully to "no grounding", never crashes boot.
    if getattr(app.state, "rag_retriever", None) is None:
        retriever = None
        azure_openai_client = None
        try:
            if AzureOpenAI is None:
                raise ImportError("Azure OpenAI client not available")

            azure_openai_client = AzureOpenAI(
                api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            retriever = HybridRetriever(
                milvus_uri=settings.milvus_db_uri,
                azure_client=azure_openai_client,
                embedding_deployment=settings.embedding_model,
                langfuse_client=get_langfuse_client(),
            )
            app.state.azure_openai_client = azure_openai_client
            app.state.rag_retriever = retriever
            set_retriever(retriever)

            # Story 5.5: Initialize input guardrail with Azure OpenAI client
            guardrail = InputGuardrail(
                azure_client=azure_openai_client,
                embedding_deployment=settings.embedding_model,
            )
            set_guardrail(guardrail)
            app.state.input_guardrail = guardrail
            owned.append("input_guardrail")

            owned.append("rag_retriever")
        except Exception as exc:
            if retriever is not None:
                try:
                    await retriever.close()
                except Exception:
                    pass
            logging.getLogger(__name__).warning("RAG retriever init failed: %s", exc)
            app.state.azure_openai_client = None
            app.state.rag_retriever = None
            set_retriever(None)
            set_guardrail(None)  # Story 5.5: Clear guardrail if Azure unavailable
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

        # Story 5.10: Wire Kafka producer to Notification Agent
        set_kafka_producer(_producer)
        logging.getLogger(__name__).info("Kafka producer wired to Notification Agent")

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

    notification_dispatcher_task: asyncio.Task | None = None
    if getattr(app.state, "notification_dispatcher", None) is None:
        brokers = [b.strip() for b in settings.kafka_brokers.split(",")]
        _dconsumer = AIOKafkaConsumer(
            "notification.events",
            bootstrap_servers=brokers,
            group_id="notification-dispatcher",
            auto_offset_reset="latest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        app.state.notification_dispatcher = _dconsumer
        owned.append("notification_dispatcher")

        async def _dispatch_notification_events() -> None:
            """Dispatch notifications based on subscriber preferences (Story 4.2).

            Consumes notification.events and:
            - Checks subscriber preferences
            - Inserts to notifications_events if opted-in (status='simulated')
            - Discards if opted-out (logs DEBUG)
            - Never crashes on DB errors (logs ERROR, commits offset)
            """
            logger = logging.getLogger(__name__)
            try:
                await _dconsumer.start()
                async for msg in _dconsumer:
                    try:
                        if msg.value is None:
                            continue

                        # Extract subscriber_id and notification_type from EventEnvelope
                        payload = msg.value.get("payload", {})
                        subscriber_id = payload.get("subscriber_id")
                        notification_type = payload.get("type")

                        if not subscriber_id or not notification_type:
                            logger.debug("Missing subscriber_id or notification_type in payload")
                            await msg.commit()  # type: ignore[attr-defined]
                            continue

                        # Query subscriber preferences
                        db = app.state.db_adapter
                        async with db.transaction() as conn:
                            prefs = await get_preferences(conn, subscriber_id)

                            # Build preference map
                            pref_map = {row["notification_type"]: row["is_enabled"] for row in prefs}

                            # Check if this type is enabled (default: True)
                            is_enabled = pref_map.get(notification_type, True)

                            if is_enabled:
                                # Subscriber opted in - insert notification event
                                channel = payload.get("channel", "sms")

                                await insert_notification_event(
                                    db=conn,
                                    subscriber_id=subscriber_id,
                                    notification_type=notification_type,
                                    channel=channel,
                                    payload=msg.value,
                                )
                                logger.debug(
                                    "Dispatched notification: subscriber=%s type=%s channel=%s",
                                    payload.get("msisdn_last4", subscriber_id[-4:]),
                                    notification_type,
                                    channel,
                                )
                            else:
                                # Subscriber opted out - discard
                                logger.debug(
                                    "Notification opted out: subscriber=%s type=%s",
                                    payload.get("msisdn_last4", subscriber_id[-4:]),
                                    notification_type,
                                )

                        # Commit offset after successful processing
                        await msg.commit()  # type: ignore[attr-defined]

                    except Exception as exc:
                        # Log ERROR but don't crash - commit offset and continue
                        logger.exception("Notification dispatch error: %s", exc)
                        try:
                            await msg.commit()  # type: ignore[attr-defined]
                        except Exception:
                            pass  # Best-effort commit

            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Notification dispatcher error: %s", exc)
            finally:
                try:
                    await _dconsumer.stop()
                except Exception:
                    pass

        notification_dispatcher_task = asyncio.create_task(_dispatch_notification_events())

    # Rate limit config (Story 4.3) — read rpm_limit from DB; falls back to 100 on error
    await RateLimitMiddleware.load_config(db=app.state.db_adapter)

    # Plan expiry reminder scheduler (Story 4.1, Task 5)
    plan_expiry_scheduler = None
    try:
        if AsyncIOScheduler is not None and CronTrigger is not None:
            plan_expiry_scheduler = AsyncIOScheduler()
            plan_expiry_scheduler.add_job(
                run_plan_expiry_check,
                trigger=CronTrigger(hour=2, minute=30, timezone="UTC"),
                args=[app.state.db_adapter, app.state.kafka_producer],
                id="plan_expiry_reminder",
                replace_existing=True,
            )
            plan_expiry_scheduler.start()
            logging.getLogger(__name__).info("plan_expiry_scheduler: started (02:30 UTC daily)")
    except Exception as exc:
        logging.getLogger(__name__).warning("plan_expiry_scheduler: failed to start: %s", exc)
        plan_expiry_scheduler = None

    data_nudge_consumer_task: asyncio.Task | None = None
    if getattr(app.state, "notification_dispatcher", None) is not None:
        logger = logging.getLogger(__name__)

        async def _run_data_nudge_consumer() -> None:
            """DATA_NUDGE consumer for data usage threshold notifications (Story 4.1, Task 4).

            Consumes cdr.enriched.filtered, filters to data CDRs, checks quota,
            publishes DATA_NUDGE events when below 10% threshold.
            """
            try:
                db = app.state.db_adapter
                producer = app.state.kafka_producer

                await run_data_nudge_consumer(db, producer)
            except asyncio.CancelledError:
                logger.info("DATA_NUDGE consumer cancelled")
            except Exception as exc:
                logger.warning("DATA_NUDGE consumer error: %s", exc)

        data_nudge_consumer_task = asyncio.create_task(_run_data_nudge_consumer())

    # Story 5.10: Background TTL poll for expired chat sessions (AC #7)
    ttl_poll_task: asyncio.Task | None = None
    if getattr(app.state, "cache_adapter", None) is not None:
        logger = logging.getLogger(__name__)

        async def _poll_expired_chat_sessions() -> None:
            """Background poll for expired chat_context:* keys (Story 5.10 AC #7).

            Every 5 minutes, SCAN for chat_context:* keys and check TTL. If a key
            has expired (TTL = -2, key deleted), fire the Conclusion Agent for that
            session. Best-effort: process restart may miss some expirations (acceptable
            for MVP per architecture.md).
            """
            try:
                conclusion_graph = get_conclusion_graph()

                if conclusion_graph is None:
                    logger.warning("TTL poll: Conclusion Agent not initialized, skipping")
                    return

                poll_interval = 300  # 5 minutes
                while True:
                    try:
                        # SCAN for chat_context:* keys
                        cursor = 0
                        expired_sessions = []

                        while True:
                            cursor, keys = await app.state.cache_adapter.client.scan(
                                cursor=cursor, match="chat_context:*", count=100
                            )

                            for key in keys:
                                # Check TTL - if key exists but TTL expired, Valkey returns -2
                                ttl = await app.state.cache_adapter.client.ttl(key)
                                if ttl == -2:  # Key expired but not yet deleted
                                    # Extract session_id from key
                                    session_id = (
                                        key.decode().split(":", 1)[1]
                                        if isinstance(key, bytes)
                                        else key.split(":", 1)[1]
                                    )
                                    expired_sessions.append(session_id)

                            if cursor == 0:
                                break

                        # Fire Conclusion Agent for each expired session
                        for session_id in expired_sessions:
                            try:
                                # Get subscriber_id from session (stored in chat_context)
                                # For MVP, we'll use a default subscriber if we can't extract it
                                # In production, this should be stored in the session metadata
                                logger.info(
                                    "TTL poll: firing Conclusion Agent for expired session %s",
                                    session_id,
                                )

                                _task = asyncio.create_task(  # noqa: RUF006
                                    conclusion_graph.ainvoke(
                                        {
                                            "session_id": session_id,
                                            "subscriber_id": "system",  # Would be extracted from session metadata in production
                                            "session_history": [],
                                            "summary": None,
                                            "trace_id": "0" * 32,
                                        }
                                    )
                                )
                            except Exception as exc:
                                logger.error(
                                    "TTL poll: failed to fire Conclusion Agent for session %s: %s",
                                    session_id,
                                    exc,
                                )

                        if expired_sessions:
                            logger.info("TTL poll: processed %d expired sessions", len(expired_sessions))

                    except asyncio.CancelledError:
                        logger.info("TTL poll: cancelled")
                        break
                    except Exception as exc:
                        logger.warning("TTL poll: error scanning for expired sessions: %s", exc)

                    # Wait before next poll
                    await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                logger.info("TTL poll: cancelled")
            except Exception as exc:
                logger.warning("TTL poll: error: %s", exc)

        ttl_poll_task = asyncio.create_task(_poll_expired_chat_sessions())

    try:
        yield
    finally:
        if plan_expiry_scheduler is not None:
            try:
                plan_expiry_scheduler.shutdown(wait=False)
            except Exception:
                pass
        if data_nudge_consumer_task is not None:
            data_nudge_consumer_task.cancel()
            try:
                await data_nudge_consumer_task
            except asyncio.CancelledError:
                pass
        if notification_dispatcher_task is not None:
            notification_dispatcher_task.cancel()
            try:
                await notification_dispatcher_task
            except asyncio.CancelledError:
                pass
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
        if ttl_poll_task is not None:
            ttl_poll_task.cancel()
            try:
                await ttl_poll_task
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
        if "rag_retriever" in owned:
            await app.state.rag_retriever.close()
            set_retriever(None)
        # Story 5.10: Clear Conclusion/Notification Agent singletons
        if "conclusion_graph" in owned:
            set_conclusion_graph(None)  # type: ignore[arg-type]
        if "notification_graph" in owned:
            set_notification_graph(None)  # type: ignore[arg-type]
        set_conclusion_adapters(None, None)  # type: ignore[arg-type]
        # Clear the Support Agent tool singletons so no in-flight tool call can
        # touch a closed adapter after shutdown (mirrors set_retriever(None)).
        set_support_adapters(None, None)  # type: ignore[arg-type]


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
    notification_dispatcher: object | None = None,
) -> FastAPI:
    """Construct the FastAPI app.

    Adapters/services may be injected (primarily for tests); when omitted they are
    created from ``settings`` during the ASGI lifespan.
    """
    _setup_tracer()
    app = FastAPI(title="SBOAI Capstone", version="0.1.0", lifespan=lifespan)
    app.add_middleware(OtelTraceMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    # Support Agent identity (Story 5.4): bind the authenticated subscriber (JWT
    # ``sub`` + MSISDN) and the chat session id onto /api/chat/* requests so the
    # tools scope queries without the LLM supplying identity (AC #2).
    app.add_middleware(SupportIdentityMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(subscriber_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(balance_router)
    app.include_router(recharge_router)
    app.include_router(notifications_router)
    app.include_router(ussd_router)
    app.include_router(support_router)
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
    app.state.notification_dispatcher = notification_dispatcher
    # CopilotKit Support Agent runtime (Story 5.4): registers POST /api/chat/*
    # (AC #1, #6) and binds the support tool singletons. The cache/DB adapters are
    # re-bound in the lifespan once the real adapters exist (tests inject fakes via
    # app.state). Azure OpenAI is optional — registration is a no-op without it so
    # the app still boots for lint/test (AC: degrade, never crash).
    setup_copilotkit(app)
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
