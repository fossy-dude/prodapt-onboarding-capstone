"""Integration test: the registration transaction against real Postgres (AC #1-#6).

Uses testcontainers with the project's custom ``docker_postgres`` image (it ships
the third-party ``pg_uuidv7`` extension), creates the required extensions, applies
the V1/V2/V3 migrations, then asserts :class:`PostgresRegistrationRepository.persist`
writes all four rows in one transaction and that the TRAI CAF audit row carries a
SHA-256 hash (never raw CAF/PII).

Marked ``slow`` + ``integration``: it needs a container runtime and is skipped by
the default ``just test`` gate (``-m "not slow"``). Run with ``pytest -m slow``.
"""

from __future__ import annotations

import pathlib

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from adapters.cognito import FakeCognitoProvider
from adapters.postgres import Psycopg3AsyncAdapter
from core.errors import DuplicateMsisdnError
from core.security import canonical_caf_hash
from services.registration import (
    REGISTRATION_STATUS,
    PostgresRegistrationRepository,
    RegistrationCommand,
    RegistrationService,
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
# The project Postgres image installs pg_uuidv7 (absent from stock postgres:16).
_IMAGE = "localhost/docker_postgres:latest"


def _cmd(registration_id: str, msisdn: str = "9876543210") -> RegistrationCommand:
    return RegistrationCommand(
        full_name="Priya Sharma",
        email="priya@example.com",
        msisdn=msisdn,
        alternate_mobile="9123456780",
        date_of_birth="1995-04-12",
        address_line1="12 MG Road",
        address_line2="",
        city="Bengaluru",
        state="Karnataka",
        pin_code="560001",
        id_proof_type="Aadhaar",
        id_proof_number="1234-5678-9012",
        consent=True,
        registration_id=registration_id,
    )


@pytest.fixture
async def db_adapter() -> Psycopg3AsyncAdapter:
    with PostgresContainer(_IMAGE) as pg:
        conninfo = (
            f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} "
            f"user={pg.username} password={pg.password}"
        )
        # Extensions + baseline migrations (the image only ships the pg_uuidv7 binary).
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            for ext in ("pg_uuidv7", "pgcrypto", "pg_trgm", "btree_gin"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            for name in ("V1__baseline_schema.sql", "V2__modified_at_trigger.sql", "V3__registration_extensions.sql"):
                await conn.execute((_MIGRATIONS / name).read_text())
        adapter = Psycopg3AsyncAdapter(conninfo)
        try:
            yield adapter
        finally:
            await adapter.close()


async def _fetch_one(db: Psycopg3AsyncAdapter, sql: str, params: tuple[object, ...] = ()) -> dict[str, object] | None:
    async with db.transaction() as conn:
        cur = await conn.execute(sql, params)
        cols = [c.name for c in cur.description] if cur.description else []
        row = await cur.fetchone()
    return dict(zip(cols, row)) if row is not None else None  # type: ignore[arg-type]


async def test_register_transaction_creates_all_rows(db_adapter: Psycopg3AsyncAdapter) -> None:
    """AC #1, #2, #4, #6: one transaction writes subscriber + registration + audit + order."""
    repo = PostgresRegistrationRepository(db_adapter)
    result = await RegistrationService(repo, FakeCognitoProvider()).register(
        _cmd("REG-20260620-deadbabe", msisdn="9876543210")
    )
    assert result.status == REGISTRATION_STATUS
    assert result.registration_id == "REG-20260620-deadbabe"

    subscriber = await _fetch_one(
        db_adapter,
        "SELECT id, msisdn, subscriber_name, cognito_user_id FROM identity_subscribers WHERE msisdn=%s",
        ("9876543210",),
    )
    assert subscriber is not None
    subscriber_id = subscriber["id"]
    assert subscriber["cognito_user_id"] == "REG-20260620-deadbabe"  # Cognito username link

    registration = await _fetch_one(
        db_adapter,
        "SELECT registration_id, status FROM identity_registrations WHERE subscriber_id=%s",
        (subscriber_id,),
    )
    assert registration is not None
    assert registration["registration_id"] == "REG-20260620-deadbabe"
    assert registration["status"] == REGISTRATION_STATUS

    audit = await _fetch_one(
        db_adapter,
        "SELECT entity_type, action, new_value FROM billing_audit_log WHERE entity_id=%s",
        (subscriber_id,),
    )
    assert audit is not None
    assert audit["entity_type"] == "TRAI_CAF"
    assert audit["action"] == "SUBMITTED"
    new_value = audit["new_value"]
    sha = new_value["caf_sha256"] if isinstance(new_value, dict) else new_value
    # The audit row stores the hash, never the raw CAF PII.
    assert sha == canonical_caf_hash(_cmd("REG-20260620-deadbabe", msisdn="9876543210").caf_payload())
    audit_json = str(new_value)
    assert "9876543210" not in audit_json
    assert "Priya Sharma" not in audit_json

    order = await _fetch_one(
        db_adapter,
        "SELECT fulfilment_status, fulfilment_type FROM ops_order_fulfilment WHERE subscriber_id=%s",
        (subscriber_id,),
    )
    assert order is not None
    assert order["fulfilment_status"] == "CREATED"  # AC #6
    assert order["fulfilment_type"] == "NEW_ACTIVATION"


async def test_register_duplicate_msisdn_raises_409_error(db_adapter: Psycopg3AsyncAdapter) -> None:
    """AC #8: a repeated MSISDN raises DuplicateMsisdnError (→ 409 in the handler)."""
    repo = PostgresRegistrationRepository(db_adapter)
    unique = "9876543211"
    await RegistrationService(repo, FakeCognitoProvider()).register(_cmd("REG-20260620-11111111", msisdn=unique))
    with pytest.raises(DuplicateMsisdnError):
        await RegistrationService(repo, FakeCognitoProvider()).register(_cmd("REG-20260620-22222222", msisdn=unique))
