#!/usr/bin/env python3
"""Idempotent Redpanda/Kafka topic provisioning for the CDR pipeline (Story 2.1).

Creates the six CDR pipeline topics with the exact partition counts mandated by
ARCH-10. Redpanda auto-creates topics on first produce, but it defaults them to
**1 partition** — which would silently break the 24-way consumer parallelism
(Story 2.2). Explicit provisioning with fixed partition counts prevents that.

Idempotent (AC #2): existing topics are listed first and left untouched —
re-running is a clean no-op (no error, no partition change). Invoked by the
``provision-topics`` justfile recipe (and from ``just up``/``just deps`` after
Redpanda is healthy), or runnable directly:

    cd cdr-pipeline && PYTHONPATH=src python scripts/provision_topics.py
"""

from __future__ import annotations

import asyncio
import logging

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from core.config import settings

logger = logging.getLogger("provision_topics")

# (topic, num_partitions, replication_factor). RF=1 for single-broker MVP Redpanda.
# Partition counts are fixed by ARCH-10 / AC #1 — do not change without updating
# the consumer pool sizing (architecture §1.4.1, §1.7.6).
TOPIC_SPEC: list[tuple[str, int, int]] = [
    ("cdr.raw", 24, 1),
    ("cdr.enriched.filtered", 24, 1),
    ("cdr.fraud.flagged", 6, 1),
    ("fraud.alerts", 6, 1),
    ("notification.events", 12, 1),
    ("cdr.dlq", 6, 1),
]


async def provision_topics(bootstrap_servers: str | None = None) -> dict[str, str]:
    """Create any missing topics from :data:`TOPIC_SPEC`; leave existing ones untouched.

    Parameters
    ----------
    bootstrap_servers : str | None
        Comma-separated broker list. Defaults to ``settings.kafka_brokers``.

    Returns
    -------
    dict[str, str]
        Mapping of topic name → ``"created"`` | ``"exists"``.
    """
    brokers = bootstrap_servers or settings.kafka_brokers
    results: dict[str, str] = {}
    admin = AIOKafkaAdminClient(bootstrap_servers=brokers, request_timeout_ms=10000)
    try:
        await admin.start()
        existing = set(await admin.list_topics())

        # CRITICAL FIX: Verify partition counts for existing topics (AC #1 compliance)
        existing_topics_to_verify = [name for name, _, _ in TOPIC_SPEC if name in existing]
        if existing_topics_to_verify:
            metadata = await admin.describe_topics(existing_topics_to_verify)
            spec_map = {name: (partitions, rf) for name, partitions, rf in TOPIC_SPEC}
            for info in metadata:
                topic = info["topic"]
                expected_partitions, _expected_rf = spec_map[topic]
                actual_partitions = len(info["partitions"])
                if actual_partitions != expected_partitions:
                    logger.error(
                        "topic %s has %d partitions but spec requires %d — topology mismatch!",
                        topic,
                        actual_partitions,
                        expected_partitions,
                    )
                    results[topic] = "mismatch"
                else:
                    logger.info("topic %s: exists (%d partitions, rf=1)", topic, actual_partitions)
                    results[topic] = "exists"

        to_create: list[NewTopic] = []
        for name, partitions, replication_factor in TOPIC_SPEC:
            if name in existing and results.get(name) != "mismatch":
                # Already handled above; skip creation
                continue
            elif name not in existing:
                to_create.append(
                    NewTopic(
                        name=name,
                        num_partitions=partitions,
                        replication_factor=replication_factor,
                    )
                )

        if to_create:
            # Defensive swallow: a concurrent run could create a topic between our
            # list_topics and create_topics (TOCTOU). Treat as "exists", not failure.
            try:
                await admin.create_topics(to_create)
            except TopicAlreadyExistsError:
                logger.warning("one or more topics created concurrently; re-checking")
                existing_after = set(await admin.list_topics())
                for topic in to_create:
                    results[topic.name] = "exists" if topic.name in existing_after else "failed"
                return results

            for topic in to_create:
                logger.info(
                    "topic %s: created (%d partitions, rf=%d)",
                    topic.name,
                    topic.num_partitions,
                    topic.replication_factor,
                )
                results[topic.name] = "created"
    finally:
        await admin.close()

    return results


def main() -> None:
    """CLI entry point: provision all topics and print a per-topic summary."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("provisioning %d topics against %s", len(TOPIC_SPEC), settings.kafka_brokers)
    # MEDIUM FIX: Add 60s timeout to prevent infinite hangs on unhealthy broker
    try:
        results: dict[str, str] = asyncio.wait_for(
            asyncio.run(provision_topics()),
            timeout=60.0,
        )
    except TimeoutError:
        logger.error("provisioning timed out after 60s — broker may be unhealthy")
        raise SystemExit(1) from None
    for name, status in results.items():
        print(f"{name}: {status}")
    # MEDIUM FIX: Check against TOPIC_SPEC, not just results (catches partial failures)
    missing = [name for name, _, _ in TOPIC_SPEC if name not in results or results[name] not in {"created", "exists"}]
    if missing:
        logger.error("provisioning incomplete for: %s", missing)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
