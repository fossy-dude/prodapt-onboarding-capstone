"""CDR pipeline consumer entrypoint (Story 2.2).

Builds the adapters, starts the ``cdr-balance-updater`` consumer (single
consumer task per process for MVP — see :mod:`consumer.batch_processor`), runs
the batch loop, and shuts down gracefully on SIGINT/SIGTERM. Run with
``python -m src.main`` / ``just cdr``.

Balance warm-up (``load_balances_from_postgres``) and balance deduction land in
Story 2.3; this entrypoint wires a no-op balance-hook seam so the consumer is
runnable end-to-end without deduction.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING, cast

from adapters.kafka import KafkaProducer, build_consumer
from adapters.redis import ValkeyAdapter
from consumer.batch_processor import BatchProcessor
from core.config import settings

if TYPE_CHECKING:
    from core.protocols.broker import MessageConsumerProtocol

logger = logging.getLogger("cdr_pipeline")


async def _run() -> None:
    """Wire adapters, run the consumer loop until signalled, then shut down."""
    cache = ValkeyAdapter(settings.valkey_url)
    producer = KafkaProducer()
    # aiokafka's getmany stubs resolve params to Unknown, so AIOKafkaConsumer
    # won't structurally satisfy MessageConsumerProtocol for the type checker —
    # but it does at runtime (getmany/commit/start/stop). Cast at this DI seam;
    # tests inject fakes/mocks that satisfy the protocol directly.
    consumer = cast(
        "MessageConsumerProtocol",
        build_consumer(
            "cdr.raw",
            group_id=settings.kafka_consumer_groups.balance_updater,
        ),
    )
    processor = BatchProcessor(consumer=consumer, producer=producer, cache=cache)

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
    try:
        loop_task = asyncio.create_task(processor.run())
        await stop_event.wait()
        # Let the in-flight batch finish + commit, then the loop exits.
        await loop_task
    finally:
        await consumer.stop()
        await producer.stop()
        await cache.close()
        logger.info("cdr consumer stopped")


def main() -> None:
    """CLI entrypoint: configure logging and run the CDR consumer until signalled."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
