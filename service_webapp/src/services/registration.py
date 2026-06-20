"""Subscriber registration orchestration (Story 1.6; architecture §1.7.1, §1.11.3).

The registration flow is a single all-or-nothing Postgres transaction that writes
four rows — ``identity_subscribers``, ``identity_registrations``, the TRAI CAF
``billing_audit_log`` row (a SHA-256 hash, never raw CAF/PII), and the initial
``ops_order_fulfilment`` order (state ``CREATED``). Cognito provisioning runs
**after** the commit (best-effort; OTP delivery is captured for the Notification
Portal) — see the compensation note on :meth:`RegistrationService.register`.

The :class:`RegistrationRepository` port lets endpoint behaviour (201 envelope, 409
duplicate, Cognito-after-commit ordering) be unit-tested with an in-memory fake,
while :class:`PostgresRegistrationRepository` is exercised by the testcontainers
integration test.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from core.errors import DuplicateMsisdnError
from core.security import canonical_caf_hash, mask_msisdn

if TYPE_CHECKING:
    from datetime import datetime

    from psycopg import AsyncConnection

    from adapters.cognito import CognitoProvider
    from adapters.postgres import Psycopg3AsyncAdapter

logger = logging.getLogger(__name__)

REGISTRATION_STATUS = "REGISTRATION_COMPLETE"
ORDER_STATE_CREATED = "CREATED"


def generate_registration_id(now: datetime) -> str:
    """``REG-{YYYYMMDD}-{8 hex}`` — 8 hex chars from 4 random bytes (AC #2).

    ``now`` is injected so tests can pin the date half; the random half comes from
    ``secrets``. Uniqueness is enforced by ``uq_identity_registrations_registration_id``.
    """
    return f"REG-{now.strftime('%Y%m%d')}-{secrets.token_hex(4)}"


@dataclass(frozen=True, slots=True)
class RegistrationCommand:
    """Validated registration payload mapped to the four DB writes + Cognito."""

    full_name: str
    email: str
    msisdn: str
    alternate_mobile: str
    # TRAI CAF (Step 2) — feeds the SHA-256 audit hash only (raw CAF is not persisted).
    date_of_birth: str
    address_line1: str
    address_line2: str
    city: str
    state: str
    pin_code: str
    id_proof_type: str
    id_proof_number: str
    consent: bool
    registration_id: str = field(default="")  # set by the service before persist

    def caf_payload(self) -> dict[str, Any]:
        """Canonicalisable CAF payload for the audit SHA-256 (AC #4)."""
        return {
            "msisdn": self.msisdn,
            "name": self.full_name,
            "date_of_birth": self.date_of_birth,
            "address": {
                "line1": self.address_line1,
                "line2": self.address_line2,
                "city": self.city,
                "state": self.state,
                "pin_code": self.pin_code,
            },
            "id_proof": {"type": self.id_proof_type, "number": self.id_proof_number},
            "consent": self.consent,
        }


@dataclass(frozen=True, slots=True)
class PersistedRegistration:
    """IDs returned once the registration transaction has committed."""

    subscriber_id: str
    registration_id: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Outcome of :meth:`RegistrationService.register` (OTP is internal-only)."""

    registration_id: str
    status: str
    subscriber_id: str
    otp: str  # captured OTP (Notification Portal / tests); never returned in the API envelope


@runtime_checkable
class RegistrationRepository(Protocol):
    """Port for the single-transaction registration persistence."""

    async def persist(self, cmd: RegistrationCommand) -> PersistedRegistration:
        """Insert subscriber + registration + audit + order in one transaction.

        Raises :class:`DuplicateMsisdnError` when the MSISDN is already registered.
        """
        ...


class PostgresRegistrationRepository:
    """Concrete repository backed by the psycopg3 adapter's transaction()."""

    def __init__(self, db: Psycopg3AsyncAdapter) -> None:
        self._db = db

    async def persist(self, cmd: RegistrationCommand) -> PersistedRegistration:
        """Insert subscriber + registration + audit + order in one transaction.

        Raises :class:`DuplicateMsisdnError` when the MSISDN is already registered
        (pre-check plus the UNIQUE constraint as a concurrency safety-net).
        """
        async with self._db.transaction() as conn:
            if await self._msisdn_exists(conn, cmd.msisdn):
                raise DuplicateMsisdnError(detail={"msisdn": mask_msisdn(cmd.msisdn)})

            subscriber_id = await self._insert_subscriber(conn, cmd)
            await self._insert_registration(conn, subscriber_id, cmd)
            await self._insert_caf_audit(conn, subscriber_id, cmd)
            await self._insert_order(conn, subscriber_id)
            # Any error rolls the transaction back (psycopg context manager).

        return PersistedRegistration(subscriber_id=str(subscriber_id), registration_id=cmd.registration_id)

    @staticmethod
    async def _msisdn_exists(conn: AsyncConnection, msisdn: str) -> bool:
        cur = await conn.execute("SELECT 1 FROM identity_subscribers WHERE msisdn = %s", (msisdn,))
        return (await cur.fetchone()) is not None

    @staticmethod
    async def _insert_subscriber(conn: AsyncConnection, cmd: RegistrationCommand) -> str:
        try:
            cur = await conn.execute(
                """
                INSERT INTO identity_subscribers (msisdn, subscriber_name, email, cognito_user_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (cmd.msisdn, cmd.full_name, cmd.email, cmd.registration_id),
            )
        except UniqueViolation as exc:
            constraint = exc.diag.constraint_name or ""
            if "msisdn" in constraint:
                raise DuplicateMsisdnError(detail={"msisdn": mask_msisdn(cmd.msisdn)}) from exc
            raise
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT INTO identity_subscribers RETURNING id returned no row")
        return str(row[0])  # RETURNING id (single column)

    @staticmethod
    async def _insert_registration(conn: AsyncConnection, subscriber_id: str, cmd: RegistrationCommand) -> None:
        cur = await conn.execute(
            """
            INSERT INTO identity_registrations (subscriber_id, registration_type, registration_id, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (subscriber_id, "NEW_ACTIVATION", cmd.registration_id, REGISTRATION_STATUS),
        )
        await cur.fetchone()

    @staticmethod
    async def _insert_caf_audit(conn: AsyncConnection, subscriber_id: str, cmd: RegistrationCommand) -> None:
        audit_detail: dict[str, Any] = {"caf_sha256": canonical_caf_hash(cmd.caf_payload())}
        await conn.execute(
            """
            INSERT INTO billing_audit_log (entity_type, entity_id, action, actor_id, actor_type, new_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                "TRAI_CAF",
                subscriber_id,
                "SUBMITTED",
                cmd.registration_id,
                "SYSTEM",
                Json(audit_detail),
            ),
        )

    @staticmethod
    async def _insert_order(conn: AsyncConnection, subscriber_id: str) -> None:
        await conn.execute(
            """
            INSERT INTO ops_order_fulfilment (subscriber_id, fulfilment_status, fulfilment_type)
            VALUES (%s, %s, %s)
            """,
            (subscriber_id, ORDER_STATE_CREATED, "NEW_ACTIVATION"),
        )


class RegistrationService:
    """Orchestrates persistence (one tx) + Cognito provisioning (after commit)."""

    def __init__(self, repo: RegistrationRepository, cognito: CognitoProvider) -> None:
        self._repo = repo
        self._cognito = cognito

    async def register(self, cmd: RegistrationCommand) -> RegistrationResult:
        """Persist the registration, then provision Cognito + dispatch the OTP.

        Persistence runs first in one transaction; Cognito runs after commit
        (best-effort — see the compensation note below). The MSISDN duplicate check
        (AC #8) surfaces as :class:`DuplicateMsisdnError` → HTTP 409.
        """
        persisted = await self._repo.persist(cmd)

        # Cognito AFTER commit (per Story 1.6 ordering). Compensation: the DB record is
        # the source of truth for registration; Cognito/OTP is retryable, so a failure
        # is logged (ERROR) and surfaced to ops rather than failing the committed
        # registration (which would leave the subscriber unable to retry the form due
        # to the 409 duplicate guard).
        otp = ""
        try:
            await self._cognito.provision_user(persisted.registration_id, cmd.alternate_mobile)
            otp = await self._cognito.start_verification(cmd.alternate_mobile)
        except Exception:
            logger.exception(
                "Cognito provisioning failed post-commit for registration %s (subscriber %s); "
                "registration is persisted — OTP dispatch must be retried",
                persisted.registration_id,
                persisted.subscriber_id,
            )

        logger.info(
            "Registration complete: registration_id=%s subscriber=%s msisdn=%s",
            persisted.registration_id,
            persisted.subscriber_id,
            mask_msisdn(cmd.msisdn),  # masked only — never the raw MSISDN (§1.11.6)
        )
        return RegistrationResult(
            registration_id=persisted.registration_id,
            status=REGISTRATION_STATUS,
            subscriber_id=persisted.subscriber_id,
            otp=otp,
        )


__all__ = [
    "ORDER_STATE_CREATED",
    "REGISTRATION_STATUS",
    "PersistedRegistration",
    "PostgresRegistrationRepository",
    "RegistrationCommand",
    "RegistrationRepository",
    "RegistrationResult",
    "RegistrationService",
    "generate_registration_id",
]
