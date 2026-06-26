"""Unit tests for the AIOKafkaConsumer factory (Story 2.2, Task 1, AC #4)."""

from __future__ import annotations

from unittest.mock import patch

from adapters.kafka import build_consumer
from core.config import settings


def test_build_consumer_uses_manual_commit_and_earliest_reset() -> None:
    """AC #4 / architecture §1.4.3: manual offsets (auto-commit off), earliest reset."""
    with patch("adapters.kafka.AIOKafkaConsumer") as mock_cls:
        build_consumer("cdr.raw", group_id="cdr-balance-updater", bootstrap_servers="localhost:9092")

    mock_cls.assert_called_once()
    args, kwargs = mock_cls.call_args
    assert args == ("cdr.raw",)  # topic subscribed positionally
    assert kwargs["bootstrap_servers"] == "localhost:9092"
    assert kwargs["group_id"] == "cdr-balance-updater"
    assert kwargs["enable_auto_commit"] is False
    assert kwargs["auto_offset_reset"] == "earliest"


def test_build_consumer_defaults_brokers_from_settings() -> None:
    """Omitting bootstrap_servers falls back to settings.kafka_brokers."""
    with patch("adapters.kafka.AIOKafkaConsumer") as mock_cls:
        build_consumer("cdr.raw", group_id="cdr-balance-updater")
    assert mock_cls.call_args.kwargs["bootstrap_servers"] == settings.kafka_brokers


def test_build_consumer_accepts_multiple_topics() -> None:
    with patch("adapters.kafka.AIOKafkaConsumer") as mock_cls:
        build_consumer("cdr.raw", "cdr.enriched.filtered", group_id="g")
    assert mock_cls.call_args.args == ("cdr.raw", "cdr.enriched.filtered")
