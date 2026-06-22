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


class BalanceFlushSettings(BaseModel):
    """Balance flusher triggers (Story 2.3, AC #3).

    Flush every ``interval_seconds`` OR when ``dirty_threshold`` msisdns are
    dirty, whichever comes first. Defaults match the architecture: 2 seconds
    or 5000 dirty keys.
    """

    interval_seconds: float = 2.0
    dirty_threshold: int = 5000


class KafkaConsumerGroups(BaseModel):
    """Named Kafka consumer-group ids, one per logical cdr-pipeline consumer.

    Each consumer (balance updater, fraud pre-screener, notifications) tracks
    its own offsets independently — so they need **distinct** group ids rather
    than sharing one. Defaults match the architecture-mandated ids; override
    per-environment via ``KAFKA_CONSUMER_GROUPS__<NAME>`` (the
    ``env_nested_delimiter='__'`` maps the nested field). Story 2.2's
    ``cdr.raw`` consumer reads :attr:`balance_updater`.
    """

    balance_updater: str = "cdr-balance-updater"
    fraud_screener: str = "cdr-fraud-screener"
    notifications: str = "cdr-notifications"


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
    kafka_consumer_groups: KafkaConsumerGroups = Field(default_factory=KafkaConsumerGroups)
    otel_service_name: str = "cdr-pipeline"

    # ── Balance flusher (Story 2.3) ─────────────────────────────────────────────
    balance_flush: BalanceFlushSettings = Field(default_factory=BalanceFlushSettings)

    # ── Cognito / management API (Story 2.5) ─────────────────────────────────
    # Identical field names + defaults to service_webapp so the ported JWTValidator
    # resolves the same JWKS URL. cognito_endpoint_url matches .env.example (LocalStack).
    cognito_endpoint_url: str = "http://localhost:4566"
    cognito_region: str = "ap-south-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    management_api_port: int = 8001


# Eager singleton: importing this module loads (and validates) all settings once.
settings = Settings()
