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
from consumer.notification_trigger import NotificationTrigger
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
    if engine.warmup_count == 0:
        # An empty wallet table means EVERY deduct would silently skip (warning
        # per CDR, no hard error) — a total billing outage. Fail fast rather than
        # start a pipeline that silently bills nobody.
        raise RuntimeError(
            "balance warm-up seeded 0 rows from billing_wallet_balances; refusing to "
            "start a billing pipeline that would silently skip every deduction"
        )
    logger.info("warmup: complete (%d balances), starting consumer + flusher", engine.warmup_count)

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

    def _crash_handler(task: asyncio.Task[object]) -> None:
        """Initiate shutdown if a long-lived task crashes.

        Without this, a crash in ``processor.run()`` leaves ``stop_event`` unset
        and ``await stop_event.wait()`` blocks forever (only SIGKILL recovers,
        skipping the final flush and losing in-flight balances/ledger rows).
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.critical("task %s crashed: %r — initiating shutdown", task.get_name(), exc)
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await producer.start()
    await consumer.start()
    await engine.run()  # Start flusher loop
    group = settings.kafka_consumer_groups.balance_updater
    logger.info("cdr consumer started (group=%s, topic=%s)", group, "cdr.raw")
    logger.info("management API starting on port %d", settings.management_api_port)

    # Notification trigger (Story 4.1) — load threshold from DB, wire into engine
    # Must be wired after producer.start() so Kafka producer is available.
    logger.info("notification_trigger: loading low_balance_threshold_paise from DB...")
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT value FROM notification_threshold_config WHERE key = %s",
                ("low_balance_threshold_paise",),
            )
            row = await cur.fetchone()
            if row is None:
                raise ValueError("low_balance_threshold_paise not found in notification_threshold_config")
            threshold_paise = int(row[0])
            logger.info("notification_trigger: threshold=%d paise (loaded from DB)", threshold_paise)

        # Inject notification trigger into existing engine
        engine.set_notification_trigger(
            NotificationTrigger(
                producer=producer,
                low_balance_threshold_paise=threshold_paise,
            )
        )
        logger.info("notification_trigger: wired into BalanceEngine")
    except Exception as exc:
        logger.warning(
            "notification_trigger: failed to load threshold from DB, continuing without notifications: %s", exc
        )
        # Keep engine without notification trigger
        pass

    mgmt_config = uvicorn.Config(
        management_app,
        host="0.0.0.0",
        port=settings.management_api_port,
        log_level="info",
    )
    mgmt_server = uvicorn.Server(mgmt_config)

    try:
        consumer_task = asyncio.create_task(processor.run(), name="cdr-consumer")
        mgmt_task = asyncio.create_task(mgmt_server.serve(), name="cdr-mgmt")
        consumer_task.add_done_callback(_crash_handler)
        mgmt_task.add_done_callback(_crash_handler)
        await stop_event.wait()
        mgmt_server.should_exit = True
        # Drain both tasks. A crashed task's exception was already logged by its
        # done-callback; gathering with return_exceptions stops it re-raising here
        # and tearing down the finally block before the final flush can run.
        outcomes = await asyncio.gather(consumer_task, mgmt_task, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.error("startup task ended with exception: %r", outcome)
    finally:
        # Shutdown order: consumer → flusher (final flush) → producer → db → cache.
        # Each close is isolated so a failure in one (e.g. consumer.stop) cannot
        # skip engine.stop() (the final flush) or the remaining closes.
        for label, close in (
            ("consumer", consumer.stop),
            ("flusher (final flush)", engine.stop),
            ("producer", producer.stop),
            ("db", db.close),
            ("cache", cache.close),
        ):
            try:
                logger.info("shutdown: stopping %s", label)
                await close()
            except Exception:
                logger.exception("shutdown: error stopping %s", label)
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
