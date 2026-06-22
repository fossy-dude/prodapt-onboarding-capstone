"""CDR-pipeline configuration singleton (Story 1.4; architecture §1.11.1).

Mirrors the ``service_webapp`` eager-load pattern, scoped to the env vars the
consumer actually needs: Postgres (balance ledger flush), Valkey (write buffer)
and Kafka (CDR ingestion). The management API + health endpoints land in Epic 2,
so only the config singleton is required here.

Import as ``from core.config import settings``. Missing **required** values raise
``ValidationError`` at import (fail-fast, AC #1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """Postgres connection settings (``DB__HOST`` → ``db.host``)."""

    host: str
    port: int = 5432
    name: str
    user: str
    password: SecretStr


class Settings(BaseSettings):
    """Top-level settings for the ``cdr-pipeline`` consumer."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        secrets_dir="/run/secrets",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Required (fail-fast when missing) ────────────────────────────────────
    db: DatabaseSettings
    valkey_url: str
    kafka_brokers: str = Field(..., min_length=1, description="Comma-separated Kafka broker list.")

    # ── Optional: consumer identity / observability ──────────────────────────
    kafka_consumer_group: str = "cdr-pipeline"
    otel_service_name: str = "cdr-pipeline"


# Eager singleton: importing this module loads (and validates) all settings once.
settings = Settings()
