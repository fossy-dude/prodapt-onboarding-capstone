"""PLAN_EXPIRY_REMINDER scheduler (Story 4.1, Task 5).

Uses APScheduler 3.x AsyncIOScheduler to run a daily cron job at 02:30 UTC
(08:00 IST) that publishes PLAN_EXPIRY_REMINDER events for subscribers whose
active plan expires within lead_days.
"""

from __future__ import annotations

import logging
from datetime import UTC, date
from typing import TYPE_CHECKING

logger = logging.getLogger("services.notification_scheduler")


async def run_plan_expiry_check(db, producer) -> None:
    """Query expiring plans and publish PLAN_EXPIRY_REMINDER events.

    Reads lead_days from notification_threshold_config at each run so that
    config changes take effect without a service restart.
    """
    lead_days = 3  # fallback default
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT value FROM notification_threshold_config WHERE key = %s",
                ("plan_expiry_reminder_days",),
            )
            row = await cur.fetchone()
            if row is not None:
                lead_days = int(row[0])
    except Exception as exc:
        logger.warning("run_plan_expiry_check: could not read lead_days (using default %d): %s", lead_days, exc)

    from uuid_extensions import uuid7

    batch_trace_id = str(uuid7())

    today = date.today()
    published_count = 0

    async with db.transaction() as conn:
        cur = await conn.execute(
            """
            SELECT
                isub.id,
                isub.msisdn,
                ps.end_date
            FROM plans_subscriptions ps
            JOIN identity_subscribers isub ON ps.subscriber_id = isub.id
            WHERE ps.status = 'active'
              AND ps.end_date BETWEEN NOW() AND NOW() + %s * INTERVAL '1 day'
            ORDER BY ps.end_date ASC
            """,
            (lead_days,),
        )

        rows = await cur.fetchall()

    logger.info("plan_expiry_check: found %d subscribers with plans expiring within %d days", len(rows), lead_days)

    import json
    from datetime import datetime
    from uuid import UUID

    for subscriber_id, msisdn, end_date in rows:
        try:
            days_remaining = (end_date - today).days
            msisdn_last4 = str(msisdn)[-4:]

            # Build notification event payload
            payload = {
                "event_type": "notification.plan",
                "event_id": str(uuid7()),
                "trace_id": batch_trace_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "type": "PLAN_EXPIRY_REMINDER",
                    "subscriber_id": str(subscriber_id),
                    "msisdn_last4": msisdn_last4,
                    "expiry_date": end_date.isoformat(),
                    "days_remaining": days_remaining,
                },
            }

            await producer.send_and_wait(
                "notification.events",
                value=payload,
                key=str(msisdn).encode(),
            )

            published_count += 1
            logger.debug(
                "Published PLAN_EXPIRY_REMINDER for subscriber_id=%s, msisdn[-4:]=%s, days_remaining=%d",
                subscriber_id,
                msisdn_last4,
                days_remaining,
            )

        except Exception as exc:
            logger.exception(
                "Error publishing PLAN_EXPIRY_REMINDER for subscriber_id=%s: %s",
                subscriber_id,
                exc,
            )

    logger.info("plan_expiry_check: published %d PLAN_EXPIRY_REMINDER events", published_count)
