"""Application configuration singleton (Story 1.4; architecture §1.11.1).

A single :class:`Settings` instance is constructed once at import time and
re-exported as :data:`settings` — the canonical way every module reads config
(``from core.config import settings``). Missing **required** values raise
``ValidationError`` immediately, so a misconfigured deployment fails fast at boot
(AC #1).

Env-key mapping matches the ``.env.example`` authored in Story 1.3:

* ``DB__HOST`` → ``settings.db.host`` (nested via ``env_nested_delimiter="__"``)
* ``VALKEY_URL``, ``KAFKA_BROKERS`` → flat top-level fields

Optional values (LLM / LangFuse / PII / OTEL) default so the service boots
without provisioning those secrets — ``LANGFUSE_ENABLED=false`` keeps tests and
dev connection-free (relevant to Story 1.5). Only the connection settings that
MUST exist for the service to operate are required.
"""

from __future__ import annotations

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """Postgres connection settings.

    Populated from the ``DB__*`` env vars by the parent :class:`Settings`
    (``env_nested_delimiter="__"``); not a ``BaseSettings`` of its own.
    """

    host: str
    port: int = 5432
    name: str
    user: str
    password: SecretStr


class Settings(BaseSettings):
    """Top-level service settings for ``service_webapp``.

    Required fields (no default) trigger fail-fast at import when absent. The
    remainder carry defaults so onboarding/tests are not blocked on unprovisioned
    downstream secrets.
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",  # DB__HOST → db.host
        env_file=".env",
        secrets_dir="/run/secrets",  # Podman secrets mount (MVP)
        extra="ignore",  # tolerate legacy aliases (REDIS_URL, KAFKA_BOOTSTRAP_SERVERS)
        case_sensitive=False,
    )

    # ── Required (fail-fast when missing) ────────────────────────────────────
    db: DatabaseSettings
    valkey_url: str
    kafka_brokers: str

    # ── Optional: LLM (Azure OpenAI) — provisioned later ─────────────────────
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-08-01-preview"

    # ── Optional: LangFuse (Story 1.5) — connection-free when disabled ───────
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""

    # ── Optional: PII encryption key (Story 1.6) ─────────────────────────────
    encryption_key: str = ""

    # ── Optional: OpenTelemetry exporter ─────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_otlp_protocol: str = "http/protobuf"
    otel_service_name: str = "service_webapp"


# Eager singleton: importing this module loads (and validates) all settings once.
settings = Settings()
