"""DATA_NUDGE consumer for data usage threshold notifications (Story 4.1, Task 4).

Subscribes to cdr.enriched.filtered Kafka topic, filters for data CDRs, and
publishes DATA_NUDGE notification events when subscriber's data allowance drops
below 10% remaining.

Runs as a background task alongside the notification_consumer_task.
"""

from __future__ import annotations

import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from uuid_extensions import uuid7

logger = logging.getLogger("services.data_nudge_consumer")

_data_nudge_notified: set[str] = set()


async def run_data_nudge_consumer(db, producer) -> None:
    """Run DATA_NUDGE consumer loop.

    Subscribes to cdr.enriched.filtered with group_id="cdr-notifications",
    filters to data CDRs only, checks data quota usage, and publishes DATA_NUDGE
    events when below 10% threshold.

    Parameters
    ----------
    db : Database connection
        Postgres connection for quota queries.
    producer : Kafka producer
        Kafka producer for publishing notification events.
    """
    import json

    from core.config import settings
    from db.billing.queries import get_active_plan_data_quota

    # Build consumer
    brokers = [b.strip() for b in settings.kafka_brokers.split(",")]
    consumer = AIOKafkaConsumer(
        "cdr.enriched.filtered",
        bootstrap_servers=brokers,
        group_id="cdr-notifications",
        auto_offset_reset="latest",
        value_deserializer=lambda v: json.loads(v.decode()),
    )

    logger.info("DATA_NUDGE consumer starting on topic=cdr.enriched.filtered, group_id=cdr-notifications")

    await consumer.start()

    try:
        while True:
            # Poll for messages (timeout_ms=1000 for 1s polling)
            records = await consumer.getmany(max_records=100, timeout_ms=1000)

            if not records:
                await asyncio.sleep(0.1)
                continue

            for partition, record_list in records.items():
                for record in record_list:
                    try:
                        # Deserialize envelope from record
                        envelope = record.value

                        # Filter to data CDRs only
                        if envelope.get("payload", {}).get("cdr_type") != "data":
                            continue

                        payload = envelope.get("payload", {})
                        subscriber_id_str = payload.get("subscriber_id")
                        if not subscriber_id_str:
                            continue

                        # Check data quota
                        quota = await get_active_plan_data_quota(db, subscriber_id_str)
                        if quota is None:
                            # No active plan or unlimited data plan
                            continue

                        data_mb_used, data_limit_mb = quota

                        # Check if below 10% threshold
                        if data_limit_mb > 0:
                            pct_remaining = max(0.0, (data_limit_mb - data_mb_used) / data_limit_mb)
                            if pct_remaining < 0.10:
                                # Dedup: only fire once per subscriber per process lifetime
                                if subscriber_id_str in _data_nudge_notified:
                                    continue
                                _data_nudge_notified.add(subscriber_id_str)

                                # Build notification envelope
                                msisdn = payload.get("from_number", "")[-4:] if payload.get("from_number") else ""

                                from models.envelope import EventEnvelope

                                notification_envelope = EventEnvelope.new(
                                    event_type="notification.balance",
                                    payload={
                                        "type": "DATA_NUDGE",
                                        "subscriber_id": subscriber_id_str,
                                        "msisdn_last4": msisdn,
                                        "data_mb_used": round(data_mb_used, 2),
                                        "data_limit_mb": data_limit_mb,
                                        "pct_remaining": round(pct_remaining, 3),
                                    },
                                    trace_id=envelope.get("trace_id", "0" * 32),
                                )

                                await producer.publish(
                                    topic="notification.events",
                                    key=payload.get("from_number", "unknown"),
                                    envelope=notification_envelope,
                                )

                                logger.info(
                                    "Published DATA_NUDGE for subscriber_id=%s, msisdn[-4:]=%s, pct_remaining=%.3f",
                                    subscriber_id_str,
                                    msisdn,
                                    pct_remaining,
                                )

                    except Exception as exc:
                        logger.exception("Error processing DATA_NUDGE CDR: %s", exc)

    except asyncio.CancelledError:
        logger.info("DATA_NUDGE consumer cancelled")
    finally:
        await consumer.stop()
        logger.info("DATA_NUDGE consumer stopped")
