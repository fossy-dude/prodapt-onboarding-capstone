"""Notification trigger for low balance and depletion events (Story 4.1, Task 2).

Publishes LOW_BALANCE and BALANCE_DEPLETED notification events to the
`notification.events` Kafka topic when a subscriber's balance crosses
thresholds. Implements idempotency via deduplication set to avoid repeated
notifications for consecutive CDRs below threshold.

Hot path constraint: the trigger check MUST use asyncio.create_task() in
BalanceEngine.deduct() — never await — to keep the hot path O(1).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from opentelemetry import trace
from uuid_extensions import uuid7

from models.envelope import EventEnvelope

if TYPE_CHECKING:
    from core.protocols.broker import MessageBrokerProtocol

logger = logging.getLogger("consumer.notification_trigger")

tracer = trace.get_tracer(__name__)


@dataclass(slots=True)
class NotificationTrigger:
    """Balance notification trigger with idempotency guard.

    Parameters
    ----------
    producer : MessageBrokerProtocol
        Kafka producer for publishing notification events.
    low_balance_threshold_paise : int
        Balance threshold in paise for LOW_BALANCE notifications (default 1000 = ₹10).
        Loaded from `notification_threshold_config` DB table at startup and cached.

    Attributes
    ----------
    _notified : set[str]
        Deduplication set tracking "{msisdn}:{event_type}" to publish once per crossing.
        Cleared when balance rises above threshold (via clear_notified).
    """

    producer: MessageBrokerProtocol
    low_balance_threshold_paise: int
    _notified: set[str] = field(default_factory=set)

    def _make_notified_key(self, msisdn: str, event_type: str) -> str:
        """Build deduplication key for msisdn + event type."""
        return f"{msisdn}:{event_type}"

    def clear_notified(self, msisdn: str) -> None:
        """Clear deduplication entries for a subscriber after recharge.

        The recharge flow (Story 3.5) calls this on successful recharge so the
        next low-balance event re-fires. Clears both LOW_BALANCE and BALANCE_DEPLETED
        entries for the msisdn.

        Parameters
        ----------
        msisdn : str
            Subscriber MSISDN to clear from deduplication set.
        """
        keys_to_remove = [key for key in self._notified if key.startswith(f"{msisdn}:")]
        for key in keys_to_remove:
            self._notified.remove(key)
        logger.debug("clear_notified: cleared %d entries for msisdn[-4:]=%s", len(keys_to_remove), msisdn[-4:])

    async def check_and_publish(
        self,
        msisdn: str,
        subscriber_id: str,
        balance_after: int,
        trace_id: str,
    ) -> None:
        """Check balance thresholds and publish notification events if crossed.

        Publishes LOW_BALANCE when 0 < balance_after < threshold.
        Publishes BALANCE_DEPLETED when balance_after <= 0.
        Each event fires once per threshold crossing (deduplicated via _notified set).

        Parameters
        ----------
        msisdn : str
            Subscriber MSISDN (used as partition key for Kafka).
        subscriber_id : str
            Subscriber UUID (included in notification payload).
        balance_after : int
            Balance in paise after the deduction (may be negative for overdraft).
        trace_id : str
            W3C trace-id (32 hex chars) for distributed tracing continuity.
        """
        # Check for BALANCE_DEPLETED (balance <= 0)
        if balance_after <= 0:
            notified_key = self._make_notified_key(msisdn, "BALANCE_DEPLETED")
            if notified_key not in self._notified:
                self._notified.add(notified_key)
                await self._publish_balance_depleted(msisdn, subscriber_id, trace_id)
                logger.info(
                    "Published BALANCE_DEPLETED for subscriber_id=%s, msisdn[-4:]=%s, balance_after=%d",
                    subscriber_id,
                    msisdn[-4:],
                    balance_after,
                )
            return

        # Check for LOW_BALANCE (0 < balance < threshold)
        if balance_after < self.low_balance_threshold_paise:
            notified_key = self._make_notified_key(msisdn, "LOW_BALANCE")
            if notified_key not in self._notified:
                self._notified.add(notified_key)
                await self._publish_low_balance(
                    msisdn=msisdn,
                    subscriber_id=subscriber_id,
                    balance_paise=balance_after,
                    threshold_paise=self.low_balance_threshold_paise,
                    trace_id=trace_id,
                )
                logger.info(
                    "Published LOW_BALANCE for subscriber_id=%s, msisdn[-4:]=%s, balance_after=%d, threshold=%d",
                    subscriber_id,
                    msisdn[-4:],
                    balance_after,
                    self.low_balance_threshold_paise,
                )
            return

        # Balance above threshold: clear LOW_BALANCE entry if present (recharge path)
        # Note: BALANCE_DEPLETED is NOT cleared here — only recharge can clear depletion
        notified_key = self._make_notified_key(msisdn, "LOW_BALANCE")
        if notified_key in self._notified:
            self._notified.remove(notified_key)
            logger.debug(
                "Cleared LOW_BALANCE entry for msisdn[-4:]=%s (balance rose above threshold)",
                msisdn[-4:],
            )

    async def _publish_low_balance(
        self,
        msisdn: str,
        subscriber_id: str,
        balance_paise: int,
        threshold_paise: int,
        trace_id: str,
    ) -> None:
        """Publish LOW_BALANCE notification event to Kafka."""
        envelope = EventEnvelope.new(
            event_type="notification.balance",
            payload={
                "type": "LOW_BALANCE",
                "subscriber_id": subscriber_id,
                "msisdn_last4": msisdn[-4:],
                "balance_paise": balance_paise,
                "threshold_paise": threshold_paise,
            },
            trace_id=trace_id,
        )

        await self.producer.publish(
            topic="notification.events",
            key=msisdn,
            envelope=envelope,
        )

    async def _publish_balance_depleted(self, msisdn: str, subscriber_id: str, trace_id: str) -> None:
        """Publish BALANCE_DEPLETED notification event to Kafka."""
        envelope = EventEnvelope.new(
            event_type="notification.balance",
            payload={
                "type": "BALANCE_DEPLETED",
                "subscriber_id": subscriber_id,
                "msisdn_last4": msisdn[-4:],
            },
            trace_id=trace_id,
        )

        await self.producer.publish(
            topic="notification.events",
            key=msisdn,
            envelope=envelope,
        )
