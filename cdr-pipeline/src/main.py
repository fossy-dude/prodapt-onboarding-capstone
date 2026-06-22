"""CDR pipeline consumer + management API entrypoint (Story 2.2 / 2.5 / 2.3).

Builds the adapters, runs warm-up (Story 2.3), starts the ``cdr-balance-updater``
consumer (single consumer task per process for MVP — see :mod:`consumer.batch_processor`),
runs the batch loop with balance deduction hook (Story 2.3), starts the async
balance flusher (Story 2.3), AND starts the management FastAPI app (Story 2.5)
on the SAME event loop so the ``WorkerController`` pause/resume is in-process.

Single-process topology (Story 2.5 Dev Notes):
  - Consumer loop and management API share one asyncio event loop.
  - ``WorkerController`` is the shared pause/resume signal (in-process asyncio.Event).
  - If the deployment splits processes, a Valkey control flag would be the fallback
    (not implemented; this story implements the in-process path).

Story 2.3 wiring (ARCH-6):
  - Warm-up: ``load_balances_from_postgres`` seeds ``balance:{msisdn}`` keys
    and builds the subscriber→msisdn index BEFORE the consumer starts.
  - Balance hook: ``BatchProcessor`` calls ``engine.deduct`` on first-sight CDRs.
  - Flusher: ``engine.run`` starts a background task; ``engine.stop`` flushes
    on shutdown.

Run with ``PYTHONPATH=src python -m main`` / ``just cdr``.
Management API runs on port ``MANAGEMENT_API_PORT`` (default 8001) / ``just cdr-admin``.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import uvicorn
from fastapi import FastAPI

from adapters.kafka import KafkaProducer, build_consumer
from adapters.postgres import Psycopg3AsyncAdapter, conninfo_from
from adapters.redis import ValkeyAdapter
from consumer.balance_writer import BalanceEngine
from consumer.batch_processor import BatchProcessor
from consumer.control import WorkerController
from core.auth import JWTValidator, _cognito_jwks_url
from core.config import settings
from core.errors import register_exception_handlers
from management.api import router as admin_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.protocols.broker import MessageConsumerProtocol

logger = logging.getLogger("cdr_pipeline")


@asynccontextmanager
async def _management_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire jwt_validator onto app.state during lifespan (Story 2.5)."""
    if getattr(app.state, "jwt_validator", None) is None:
        app.state.jwt_validator = JWTValidator(_cognito_jwks_url(settings))
    try:
        yield
    finally:
        pass


def create_management_app(*, worker_controller: WorkerController) -> FastAPI:
    """Build the management FastAPI app with the admin router."""
    app = FastAPI(
        title="CDR Pipeline Management API",
        version="0.1.0",
        lifespan=_management_lifespan,
    )
    register_exception_handlers(app)
    app.include_router(admin_router)
    app.state.worker_controller = worker_controller
    return app


async def _run() -> None:
    """Wire adapters, warm-up balances, run consumer + flusher + management API."""
    controller = WorkerController()
    cache = ValkeyAdapter(settings.valkey_url)
    db = Psycopg3AsyncAdapter(conninfo_from(settings.db))
    producer = KafkaProducer()
    consumer = cast(
        "MessageConsumerProtocol",
        build_consumer(
            "cdr.raw",
            group_id=settings.kafka_consumer_groups.balance_updater,
        ),
    )

    # Balance engine (Story 2.3) — warm-up + flusher
    engine = BalanceEngine(
        cache,
        db,
        flush_interval=settings.balance_flush.interval_seconds,
        flush_dirty_threshold=settings.balance_flush.dirty_threshold,
    )

    # Warm-up: seed balance:{msisdn} keys + build subscriber→msisdn index
    # MUST complete before consumer starts (ARCH-6)
    logger.info("warmup: loading balances from Postgres...")
    await engine.warmup()
    logger.info("warmup: complete, starting consumer + flusher")

    # Batch processor with balance deduction hook (Story 2.3)
    processor = BatchProcessor(
        consumer=consumer,
        producer=producer,
        cache=cache,
        controller=controller,
        balance_hook=engine.deduct,
    )

    management_app = create_management_app(worker_controller=controller)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received — finishing current batch, then stopping")
        processor.stop()
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await producer.start()
    await consumer.start()
    await engine.run()  # Start flusher loop
    group = settings.kafka_consumer_groups.balance_updater
    logger.info("cdr consumer started (group=%s, topic=%s)", group, "cdr.raw")
    logger.info("management API starting on port %d", settings.management_api_port)

    mgmt_config = uvicorn.Config(
        management_app,
        host="0.0.0.0",
        port=settings.management_api_port,
        log_level="info",
    )
    mgmt_server = uvicorn.Server(mgmt_config)

    try:
        consumer_task = asyncio.create_task(processor.run())
        mgmt_task = asyncio.create_task(mgmt_server.serve())
        await stop_event.wait()
        mgmt_server.should_exit = True
        await consumer_task
        await mgmt_task
    finally:
        # Shutdown order: consumer → flusher (final flush) → producer → db → cache
        logger.info("shutdown: stopping consumer")
        await consumer.stop()
        logger.info("shutdown: stopping flusher (final flush)")
        await engine.stop()
        await producer.stop()
        await db.close()
        await cache.close()
        logger.info("shutdown: complete")


def main() -> None:
    """CLI entrypoint: configure logging and run the CDR consumer + management API."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
