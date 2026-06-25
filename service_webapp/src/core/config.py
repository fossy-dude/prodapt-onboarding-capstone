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

    # ── Optional: LLM / Embedding (Azure OpenAI) — override in .env ──────────
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-08-01-preview"

    # ── Optional: Azure OpenAI deployment names (Story 5.2) ───────────────────
    # Deployment names (NOT model names) — the user sets these to match their
    # Azure portal deployments. ``chat_deployment_mini`` is the cheaper deployment
    # used for judge/eval calls; ``chat_deployment`` is the primary agent
    # deployment (wired in Story 5.4). [Source: architecture.md:98]
    chat_deployment_mini: str = "gpt-5.4-mini"
    chat_deployment: str = "gpt-5.4"

    # ── Embedding config (Story 2.7) ──────────────────────────────────────────
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # ── Milvus Lite (Story 2.7) ───────────────────────────────────────────────
    # Env var: MILVUS_DB_URI (avoids conflict with pymilvus's own MILVUS_URI var)
    milvus_db_uri: str = "/app/data/milvus/sboai.db"

    # ── Optional: LangFuse (Story 1.5) — connection-free when disabled ───────
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""

    # ── Optional: PII encryption key (Story 1.6) ─────────────────────────────
    # Application-layer AES-256 key for PII consumed/shared outside the DB
    # (NOT at-rest column encryption — per user decision 2026-06-20). 32-byte hex.
    encryption_key: str = ""

    # ── Optional: AWS Cognito via MiniStack/LocalStack (Story 1.6/1.8) ────────
    # MiniStack (LocalStack-compatible) emulates Cognito on a single endpoint.
    # Infra is provisioned by the docker compose stack; the app just routes here.
    cognito_endpoint_url: str = "http://localhost:4566"
    cognito_region: str = "ap-south-1"
    cognito_user_pool_name: str = "sboai-subscribers"
    cognito_user_pool_id: str = ""  # written by scripts/provision_cognito.py (just deps)
    cognito_client_id: str = ""  # written by scripts/provision_cognito.py (just deps)
    aws_access_key_id: str = "test"  # LocalStack accepts dummy credentials
    aws_secret_access_key: str = "test"

    # ── Optional: OTP step-up (Story 1.8) ────────────────────────────────────
    # Valkey key TTL (seconds) for mid-session step-up OTP (otp:{msisdn}).
    # Distinct from the login OTP below.
    otp_step_up_ttl_seconds: int = 300

    # ── Optional: passwordless login OTP (Epic 3) ────────────────────────────
    # Valkey key TTL for login OTP (login_otp:{identifier}). Distinct prefix from step-up.
    otp_login_ttl_seconds: int = 300
    # Allow anonymous WebSocket connections to /ws/notifications (dev bootstrap only).
    notification_portal_open_in_dev: bool = False
    # Deterministic per-user password seeded by provision_cognito.py for ADMIN_NO_SRP_AUTH.
    # Interpolated as: seed.format(username=username)
    cognito_local_admin_password_seed: str = "SboAI-Local-{username}-Pw1!"
    # Static password used when auto-provisioning seed subscribers (phone-number login path).
    # All phone-number users who were never explicitly provisioned in Cognito share this password.
    cognito_phone_user_default_password: str = "SboAI-Phone-Default-1!"

    # ── Optional: OpenTelemetry exporter ─────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_otlp_protocol: str = "http/protobuf"
    otel_service_name: str = "service_webapp"

    # ── Optional: Dev mode (local / CI only) ─────────────────────────────────
    # Skips RS256 signature verification against the Cognito JWKS endpoint.
    # LocalStack Community does not serve /.well-known/jwks.json, so JWKS fetches
    # fail in local dev. Claims (expiry, groups, sub) are still validated.
    # Never set True in production.
    dev_mode: bool = False

    # ── Optional: Rate limiting (Story 4.3) ───────────────────────────────────
    # Default False (MVP stub — architecture §1.7.3: "not in MVP"). Set True to
    # activate Valkey-backed per-subscriber-per-channel 100 RPM enforcement.
    rate_limiting_enabled: bool = False


# Eager singleton: importing this module loads (and validates) all settings once.
settings = Settings()
