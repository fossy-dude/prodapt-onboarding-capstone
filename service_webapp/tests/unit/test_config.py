"""Unit tests for the service_webapp config singleton (AC #1).

Fail-fast is the core contract: a missing REQUIRED value must raise a descriptive
``ValidationError`` at construction time. Optional secrets default so the service
boots without provisioning LLM/LangFuse/PII keys.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import DatabaseSettings, Settings

# A complete minimal env map that satisfies every required field.
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
    """Populate every required env var (no .env file, no secrets dir)."""
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_settings_loads_when_required_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """All required vars present → Settings() constructs and maps nested + flat keys."""
    _set_required_env(monkeypatch)
    # pymilvus imports load_dotenv() at module level, polluting os.environ with .env
    # values from any test that imported pymilvus before this one. Clear optional
    # secrets so the default-value assertions below are order-independent.
    for key in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"):
        monkeypatch.delenv(key, raising=False)
    cfg = Settings(_env_file=None, _secrets_dir=None)

    # Nested DB__* mapping.
    assert isinstance(cfg.db, DatabaseSettings)
    assert cfg.db.host == "localhost"
    assert cfg.db.port == 5432
    assert cfg.db.name == "sboai_test"

    # Flat keys.
    assert cfg.valkey_url == "redis://localhost:6379"
    assert cfg.kafka_brokers == "localhost:9092"

    # Optional defaults keep the service bootable without provisioning secrets.
    assert cfg.langfuse_enabled is False
    assert cfg.azure_openai_api_key == ""


@pytest.mark.parametrize(
    "missing_key", ["DB__HOST", "DB__NAME", "DB__USER", "DB__PASSWORD", "VALKEY_URL", "KAFKA_BROKERS"]
)
def test_settings_raises_when_required_missing(monkeypatch: pytest.MonkeyPatch, missing_key: str) -> None:
    """A single missing required var → descriptive ValidationError (fail-fast, AC #1)."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, _secrets_dir=None)

    # The error must name the offending field so ops can fix it.
    message = str(exc_info.value)
    missing_field = missing_key.lower().replace("__", ".")
    assert missing_field in message.lower(), f"expected '{missing_field}' in error: {message}"


def test_settings_singleton_is_constructed_at_import() -> None:
    """The module-level singleton exists (eager load happened at import)."""
    from core.config import settings

    assert isinstance(settings, Settings)
    assert isinstance(settings.db, DatabaseSettings)
