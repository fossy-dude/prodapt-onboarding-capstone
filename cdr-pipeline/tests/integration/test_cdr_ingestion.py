"""Integration test: CDR ingestion — dedup + forward + commit-after-batch (Story 2.2).

Slow / integration: needs a container runtime (Podman/Docker socket) and uses
testcontainers Redpanda + Valkey — the REAL broker + cache, NOT mocks. Skipped by
the default ``just test-cdr`` gate (``-m "not slow"``). Run with rootless Podman:

    DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
        cd cdr-pipeline && uvx --with tox-uv tox -e test -- -m slow
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from testcontainers.kafka import RedpandaContainer
from testcontainers.redis import RedisContainer

from adapters.kafka import KafkaProducer, build_consumer
from adapters.redis import ValkeyAdapter
from consumer.batch_processor import BatchProcessor
from consumer.dedup import dedup_stats
from models.envelope import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_SUBSCRIBER = UUID("0192a4d0-1234-7000-8000-000000000abc")
_DUP_CDR_ID = UUID("0192a4d0-0001-7000-8000-000000000001")
_OTHER_CDR_ID = UUID("0192a4d0-0001-7000-8000-000000000002")
_SESSION = UUID("0192a4d0-abcd-7000-8000-000000000def")
_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TRACE = "0123456789abcdef0123456789abcdef"

_TOPIC_SPEC = [
    NewTopic("cdr.raw", 24, 1),
    NewTopic("cdr.enriched.filtered", 24, 1),
    NewTopic("cdr.dlq", 6, 1),
]


def _cdr(cdr_id: UUID) -> dict:
    return {
        "cdr_id": str(cdr_id),
        "session_id": str(_SESSION),
        "subscriber_id": str(_SUBSCRIBER),
        "cdr_type": "sms",
        "telecom_circle": "KA",
        "cost_paise": 25,
        "start_time": _START.isoformat(),
        "message_direction": "MT",
        "sms_status": "delivered",
    }


async def _provision(brokers: str) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=brokers)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        to_create = [t for t in _TOPIC_SPEC if t.name not in existing]
        if to_create:
            await admin.create_topics(to_create)
    finally:
        await admin.close()


async def _run_until(
    processor: BatchProcessor,
    predicate: Callable[[], bool],
    *,
    settle_seconds: float = 2.0,
    timeout_seconds: float = 30.0,
) -> None:
    """Run the processor until ``predicate`` is true, settle, then stop gracefully."""
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(processor.run())
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline and not predicate():
        await asyncio.sleep(0.3)
    await asyncio.sleep(settle_seconds)  # let in-flight forwards flush
    processor.stop()
    await asyncio.wait_for(task, timeout=10)


@pytest.fixture
def redpanda():
    with RedpandaContainer(image="docker.io/redpandadata/redpanda:v24.2.1") as container:
        yield container


@pytest.fixture
def valkey():
    with RedisContainer(image="docker.io/valkey/valkey:8-alpine") as container:
        yield container


async def test_duplicate_pair_deduped_offsets_committed(redpanda: RedpandaContainer, valkey: RedisContainer) -> None:
    """AC #1/#2/#6: a duplicate pair yields one forward; restart reprocesses nothing."""
    brokers = redpanda.get_bootstrap_server()
    valkey_url = f"redis://{valkey.get_container_host_ip()}:{valkey.get_exposed_port(6379)}"
    await _provision(brokers)

    dedup_stats.reset()

    # Publish: two events with the SAME cdr_id (the duplicate pair) + one distinct.
    producer = KafkaProducer(bootstrap_servers=brokers)
    await producer.start()
    try:
        for cdr_id in (_DUP_CDR_ID, _DUP_CDR_ID, _OTHER_CDR_ID):
            env = EventEnvelope.new(event_type="cdr.raw", payload=_cdr(cdr_id), trace_id=_TRACE)
            await producer.publish("cdr.raw", key=str(_SUBSCRIBER), envelope=env)
    finally:
        await producer.stop()

    # Run 1: consume + dedup + forward + commit.
    cache = ValkeyAdapter(valkey_url)
    consumer = build_consumer("cdr.raw", group_id="it-cdr-balance-updater-2-2", bootstrap_servers=brokers)
    fwd_producer = KafkaProducer(bootstrap_servers=brokers)
    processor = BatchProcessor(consumer=consumer, producer=fwd_producer, cache=cache)
    await fwd_producer.start()
    await consumer.start()
    try:
        # The duplicate pair → dedup_stats hits 1 once the 2nd identical cdr_id is seen.
        await _run_until(processor, lambda: dedup_stats.deduplicated >= 1)
    finally:
        await consumer.stop()
        await fwd_producer.stop()
        await cache.close()

    assert dedup_stats.deduplicated == 1  # exactly the duplicate of the pair

    # Read cdr.enriched.filtered: exactly one of the duplicate pair + the distinct one.
    sink = AIOKafkaConsumer(
        "cdr.enriched.filtered",
        bootstrap_servers=brokers,
        group_id="it-enriched-sink-2-2",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await sink.start()
    forwarded_ids: set[str] = set()
    try:
        batch = await sink.getmany(timeout_ms=3000, max_records=10)
        for records in batch.values():
            for rec in records:
                env = EventEnvelope.model_validate_json(rec.value)
                forwarded_ids.add(env.payload["cdr_id"])
    finally:
        await sink.stop()
    assert forwarded_ids == {str(_DUP_CDR_ID), str(_OTHER_CDR_ID)}  # one of the pair + the other

    # Run 2: restart in the SAME group. Committed offsets ⇒ nothing re-delivered ⇒
    # no reprocessing (dedup_stats stays 0). Had the batch been uncommitted, the
    # redelivered records would all hit the dedup guard and increment the counter.
    dedup_stats.reset()
    consumer2 = build_consumer("cdr.raw", group_id="it-cdr-balance-updater-2-2", bootstrap_servers=brokers)
    fwd_producer2 = KafkaProducer(bootstrap_servers=brokers)
    processor2 = BatchProcessor(consumer=consumer2, producer=fwd_producer2, cache=ValkeyAdapter(valkey_url))
    await fwd_producer2.start()
    await consumer2.start()
    try:
        await _run_until(processor2, lambda: False, settle_seconds=3.0, timeout_seconds=8.0)
    finally:
        await consumer2.stop()
        await fwd_producer2.stop()

    assert dedup_stats.deduplicated == 0  # no committed re-processing on restart
