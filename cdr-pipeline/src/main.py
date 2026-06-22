"""CDR pipeline consumer + management API entrypoint (Story 2.2 / 2.5).

Builds the adapters, starts the ``cdr-balance-updater`` consumer (single
consumer task per process for MVP — see :mod:`consumer.batch_processor`), runs
the batch loop, AND starts the management FastAPI app (Story 2.5) on the SAME
event loop so the ``WorkerController`` pause/resume is in-process.

Single-process topology (Story 2.5 Dev Notes):
  - Consumer loop and management API share one asyncio event loop.
  - ``WorkerController`` is the shared pause/resume signal (in-process asyncio.Event).
  - If the deployment splits processes, a Valkey control flag would be the fallback
    (not implemented; this story implements the in-process path).

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
from adapters.redis import ValkeyAdapter
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
    """Wire adapters, run the consumer loop + management API until signalled."""
    controller = WorkerController()
    cache = ValkeyAdapter(settings.valkey_url)
    producer = KafkaProducer()
    consumer = cast(
        "MessageConsumerProtocol",
        build_consumer(
            "cdr.raw",
            group_id=settings.kafka_consumer_groups.balance_updater,
        ),
    )
    processor = BatchProcessor(
        consumer=consumer,
        producer=producer,
        cache=cache,
        controller=controller,
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
        await consumer.stop()
        await producer.stop()
        await cache.close()
        logger.info("cdr consumer stopped")


def main() -> None:
    """CLI entrypoint: configure logging and run the CDR consumer + management API."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
