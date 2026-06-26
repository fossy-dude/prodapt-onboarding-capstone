"""Startup balance warm-up from Postgres (Story 2.3, Task 3, AC #5).

Loads all subscriber balances from ``billing_wallet_balances`` into Valkey
as ``balance:{msisdn}``` keys and builds the in-process ``subscriber_id → msisdn``
lookup index. Must complete in < 5s for 300K rows (AC #5) and run BEFORE the
consumer loop starts (ARCH-6) so an ``INCRBY`` on a missing key never corrupts
the balance (starting from 0).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol

logger = logging.getLogger("consumer.startup")


@dataclass(frozen=True, slots=True)
class BalanceWarmupState:
    """Result of the balance warm-up: the subscriber→msisdn index and count."""

    subscriber_to_msisdn: Mapping[str, str]  # subscriber_id (UUID str) → msisdn
    msisdn_to_subscriber: Mapping[str, str]  # msisdn → subscriber_id (UUID str)
    count: int  # number of balances seeded


async def load_balances_from_postgres(
    db: DatabaseProtocol,
    cache: CacheProtocol,
) -> BalanceWarmupState:
    """Bulk-read ``billing_wallet_balances`` and seed Valkey ``balance:{msisdn}``` keys.

    Queries ``SELECT subscriber_id, msisdn, balance_paise FROM billing_wallet_balances``
    (the denormalised ``msisdn`` column enables fast warm-up). Seeds each ``balance:{msisdn}``
    via ``cache.set_many`` (pipelined, no TTL). Returns the ``subscriber_id → msisdn`` index
    so the hot path can resolve msisdn from a CDR without a DB lookup.

    Must complete in < 5s for 300K rows (AC #5). Postgres query is single-pass
    and Valkey ``set_many`` uses 5000-record pipelines.

    Parameters
    ----------
    db : DatabaseProtocol
        Postgres adapter with ``transaction`` context.
    cache : CacheProtocol
        Valkey adapter with ``set_many`` (bulk SET, no expiry).

    Returns
    -------
    BalanceWarmupState
        ``subscriber_id → msisdn`` index (both as strings) + ``msisdn → subscriber_id``
        reverse index (for flusher upserts) + count of balances seeded.
    """
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT subscriber_id, msisdn, balance_paise FROM billing_wallet_balances")
        rows = await cur.fetchall()

    if not rows:
        logger.info("warmup: no balances found in billing_wallet_balances")
        return BalanceWarmupState(subscriber_to_msisdn={}, msisdn_to_subscriber={}, count=0)

    # Build the balance:{msisdn} dict for cache.set_many
    balance_dict: dict[str, int] = {}
    subscriber_to_msisdn: dict[str, str] = {}
    msisdn_to_subscriber: dict[str, str] = {}

    for row in rows:
        subscriber_id, msisdn, balance_paise = row
        sub_id_str = str(subscriber_id)
        msisdn_str = str(msisdn)
        key = f"balance:{msisdn_str}"
        balance_dict[key] = balance_paise
        subscriber_to_msisdn[sub_id_str] = msisdn_str
        msisdn_to_subscriber[msisdn_str] = sub_id_str

    await cache.set_many(balance_dict)

    logger.info(
        "warmup: seeded %d balance keys (%d msisdns → subscriber_id index built)",
        len(balance_dict),
        len(subscriber_to_msisdn),
    )

    return BalanceWarmupState(
        subscriber_to_msisdn=subscriber_to_msisdn,
        msisdn_to_subscriber=msisdn_to_subscriber,
        count=len(balance_dict),
    )


__all__ = ["BalanceWarmupState", "load_balances_from_postgres"]
