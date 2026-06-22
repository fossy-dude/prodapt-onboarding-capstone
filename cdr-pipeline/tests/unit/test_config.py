"""Unit tests for the cdr-pipeline config singleton (AC #1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import DatabaseSettings, KafkaConsumerGroups, Settings

REQUIRED_ENV = {
    "DB__HOST": "localhost",
    "DB__PORT": "5432",
    "DB__NAME": "sboai_test",
    "DB__USER": "sboai_app",
    "DB__PASSWORD": "change_me_app",
    "VALKEY_URL": "redis://localhost:6379",
    "KAFKA_BROKERS": "localhost:9092",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_settings_loads_when_required_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    cfg = Settings(_env_file=None, _secrets_dir=None)

    assert isinstance(cfg.db, DatabaseSettings)
    assert cfg.db.host == "localhost"
    assert cfg.valkey_url == "redis://localhost:6379"
    assert cfg.kafka_brokers == "localhost:9092"
    assert isinstance(cfg.kafka_consumer_groups, KafkaConsumerGroups)
    # Each logical consumer gets a distinct default group id (architecture-mandated).
    assert cfg.kafka_consumer_groups.balance_updater == "cdr-balance-updater"
    assert cfg.kafka_consumer_groups.fraud_screener == "cdr-fraud-screener"
    assert cfg.kafka_consumer_groups.notifications == "cdr-notifications"


def test_kafka_consumer_groups_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested groups are env-overridable per consumer (KAFKA_CONSUMER_GROUPS__<NAME>)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("KAFKA_CONSUMER_GROUPS__BALANCE_UPDATER", "custom-balance-group")
    cfg = Settings(_env_file=None, _secrets_dir=None)
    assert cfg.kafka_consumer_groups.balance_updater == "custom-balance-group"
    # Untouched groups keep their defaults.
    assert cfg.kafka_consumer_groups.fraud_screener == "cdr-fraud-screener"


@pytest.mark.parametrize("missing_key", ["DB__HOST", "DB__NAME", "VALKEY_URL", "KAFKA_BROKERS"])
def test_settings_raises_when_required_missing(monkeypatch: pytest.MonkeyPatch, missing_key: str) -> None:
    """A single missing required var → descriptive ValidationError (fail-fast, AC #1)."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, _secrets_dir=None)

    missing_field = missing_key.lower().replace("__", ".")
    assert missing_field in str(exc_info.value).lower()


def test_settings_singleton_is_constructed_at_import() -> None:
    from core.config import settings

    assert isinstance(settings, Settings)
