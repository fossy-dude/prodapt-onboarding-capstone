"""Unit tests for the CDR dedup guard (Story 2.2, Task 2, AC #1, NFR-9).

The cache is mocked; the high-value assertions are the dedup decision logic
(first sight vs duplicate), the exact ``dedup:{cdr_id}`` key + 24h TTL, and the
in-process counter.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from consumer.dedup import dedup_key, dedup_stats, is_duplicate

_CDR_ID = UUID("0192a4d0-0001-7000-8000-000000000001")


def _cache(set_nx_return: bool) -> AsyncMock:
    cache = AsyncMock()
    cache.set_nx.return_value = set_nx_return
    return cache


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    dedup_stats.reset()
    yield
    dedup_stats.reset()


def test_dedup_key_domain() -> None:
    """ARCH-5: the key domain is exactly dedup:{cdr_id}."""
    assert dedup_key(_CDR_ID) == f"dedup:{_CDR_ID}"


async def test_first_sight_is_not_duplicate_and_sets_key() -> None:
    """SET NX succeeds (first sight) → not a duplicate; key + TTL sent correctly."""
    cache = _cache(set_nx_return=True)

    assert await is_duplicate(cache, _CDR_ID) is False

    cache.set_nx.assert_awaited_once_with(f"dedup:{_CDR_ID}", "1", ex=86400)
    assert dedup_stats.deduplicated == 0


async def test_second_sight_is_duplicate_and_counted() -> None:
    """SET NX fails (key existed) → duplicate, counter incremented."""
    cache = _cache(set_nx_return=False)

    assert await is_duplicate(cache, _CDR_ID) is True
    assert dedup_stats.deduplicated == 1

    # A second duplicate increments again.
    await is_duplicate(cache, _CDR_ID)
    assert dedup_stats.deduplicated == 2


async def test_duplicate_logs_cdr_id_at_debug_not_pii(caplog: pytest.LogCaptureFixture) -> None:
    """Duplicate log carries cdr_id only (never MSISDN / PII), at DEBUG level."""
    cache = _cache(set_nx_return=False)
    caplog.set_level(logging.DEBUG, logger="consumer.dedup")

    assert await is_duplicate(cache, _CDR_ID) is True

    record = next(r for r in caplog.records if r.name == "consumer.dedup")
    assert record.levelno == logging.DEBUG
    assert str(_CDR_ID) in record.getMessage()
