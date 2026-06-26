"""Integration test: charge breakdown query with real Postgres (Story 5.7; AC #2).

Testcontainers: Postgres (project image) with V1 migrations. Seeds a subscriber,
plan subscription, billing CDR event, and billing transaction, then verifies that
get_charge_breakdown returns the correct fields and values.

Marked ``slow`` + ``integration``: requires a container runtime (Podman/Docker).
Skipped by default; run with ``pytest --run-slow`` or ``--run-integration``.
"""

from __future__ import annotations

import pathlib
import uuid

import psycopg
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"
_PG_IMAGE = "localhost/docker_postgres:latest"


@pytest.fixture(scope="module")
async def seeded_db():
    """Postgres with V1 migrations seeded with test data for charge breakdown."""
    with PostgresContainer(_PG_IMAGE) as pg:
        conninfo = (
            f"host=127.0.0.1 port={pg.get_exposed_port(5432)} dbname={pg.dbname} "
            f"user={pg.username} password={pg.password}"
        )
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            # Create extensions
            for ext in ("pg_uuidv7", "pgcrypto", "pg_trgm", "btree_gin"):
                await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')

            # Run V1 migrations only (Story 5.7 requires no new migration)
            await conn.execute((_MIGRATIONS / "V1__baseline_schema.sql").read_text())

            # Seed test data
            msisdn = "9988776655"
            plan_id = uuid.uuid4()
            subscription_id = uuid.uuid4()
            subscriber_id = uuid.uuid4()
            cdr_id = uuid.uuid7()

            # Insert plan
            await conn.execute(
                """INSERT INTO plans_plans (id, plan_name, plan_code, price_paise, validity_days,
                   data_limit_mb, voice_minutes, sms_count, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (plan_id, "Test Plan", "TEST", 10000, 28, 10240, 600, 100, True),
            )

            # Insert subscriber
            await conn.execute(
                """INSERT INTO identity_subscribers (id, msisdn, status, plan_id)
                   VALUES (%s, %s, %s, %s)""",
                (subscriber_id, msisdn, "active", plan_id),
            )

            # Insert active subscription
            await conn.execute(
                """INSERT INTO plans_subscriptions (id, subscriber_id, plan_id, start_date, status)
                   VALUES (%s, %s, %s, NOW(), %s)""",
                (subscription_id, subscriber_id, plan_id, "active"),
            )

            # Insert wallet balance
            await conn.execute(
                """INSERT INTO billing_wallet_balances (subscriber_id, msisdn, balance_paise)
                   VALUES (%s, %s, %s)""",
                (subscriber_id, msisdn, 5000),
            )

            # Insert billing CDR event (voice call - 125 seconds = 2m 5s)
            await conn.execute(
                """INSERT INTO billing_cdr_events
                   (id, session_id, subscriber_id, cdr_type, telecom_circle, cost_paise, status,
                    start_time, end_time, from_number, to_number, duration_seconds)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    cdr_id,
                    uuid.uuid7(),
                    subscriber_id,
                    "voice",
                    "KA",
                    250,  # charge_paise
                    "rated",
                    psycopg.Transaction.now() - psycopg.Interval(hours=1),
                    psycopg.Transaction.now() - psycopg.Interval(hours=1) + psycopg.Interval(seconds=125),
                    "9988776655",
                    "1122334455",
                    125,  # duration_seconds
                ),
            )

            # Insert billing transaction for balance impact
            await conn.execute(
                """INSERT INTO billing_transactions
                   (subscriber_id, transaction_type, amount_paise, reference_type, reference_id,
                    balance_before_paise, balance_after_paise, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    subscriber_id,
                    "deduction",
                    -250,
                    "cdr",
                    cdr_id,
                    5000,
                    4750,
                    "Voice call deduction",
                ),
            )

            yield {
                "conn": conn,
                "subscriber_id": subscriber_id,
                "cdr_id": cdr_id,
                "plan_id": plan_id,
            }


class TestChargeBreakdownIntegration:
    """Integration tests for get_charge_breakdown with real Postgres."""

    @pytest.mark.asyncio
    async def test_get_charge_breakdown_voice_event(self, seeded_db: dict) -> None:
        """Query should return complete charge breakdown for voice CDR event."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]
        cdr_id = seeded_db["cdr_id"]

        # Query charge breakdown
        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(cdr_id))

        # Verify structure
        assert breakdown is not None
        assert isinstance(breakdown, dict)

        # Verify required fields
        assert "cdr_id" in breakdown
        assert "event_type" in breakdown
        assert "duration_or_data" in breakdown
        assert "rate_per_unit" in breakdown
        assert "charge_paise" in breakdown
        assert "balance_before" in breakdown
        assert "balance_after" in breakdown

        # Verify values
        assert breakdown["event_type"] == "voice"
        assert breakdown["charge_paise"] == 250
        assert breakdown["balance_before"] == 5000
        assert breakdown["balance_after"] == 4750
        assert breakdown["rate_per_unit"] > 0  # Should have a rate

        # Verify duration formatting (125 seconds = 2m 5s)
        assert "2m" in breakdown["duration_or_data"]
        assert "5s" in breakdown["duration_or_data"]

    @pytest.mark.asyncio
    async def test_get_charge_breakdown_cdr_not_found(self, seeded_db: dict) -> None:
        """Query should return None for non-existent CDR reference."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]
        fake_cdr_id = uuid.uuid7()

        # Query with non-existent CDR
        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(fake_cdr_id))

        # Should return None
        assert breakdown is None

    @pytest.mark.asyncio
    async def test_get_charge_breakdown_wrong_subscriber(self, seeded_db: dict) -> None:
        """Query should return None when CDR exists but belongs to different subscriber."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        cdr_id = seeded_db["cdr_id"]
        wrong_subscriber_id = uuid.uuid4()

        # Query with wrong subscriber_id
        breakdown = await get_charge_breakdown(conn, str(wrong_subscriber_id), str(cdr_id))

        # Should return None (subscriber isolation)
        assert breakdown is None

    @pytest.mark.asyncio
    async def test_get_charge_breakdown_balance_impact(self, seeded_db: dict) -> None:
        """Balance after should equal balance before minus charge."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]
        cdr_id = seeded_db["cdr_id"]

        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(cdr_id))

        assert breakdown is not None
        balance_before = breakdown["balance_before"]
        charge = breakdown["charge_paise"]
        balance_after = breakdown["balance_after"]

        # Verify balance calculation
        assert balance_after == balance_before - charge

    @pytest.mark.asyncio
    async def test_get_charge_breakdown_rate_fields(self, seeded_db: dict) -> None:
        """Query should return rate_per_unit as integer (paise)."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]
        cdr_id = seeded_db["cdr_id"]

        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(cdr_id))

        assert breakdown is not None
        rate = breakdown["rate_per_unit"]

        # Rate should be a positive integer (paise per unit)
        assert isinstance(rate, int)
        assert rate > 0

        # For voice, default rate is 50 paise/minute if not configured
        assert rate >= 0


class TestChargeBreakdownDataEvent:
    """Integration tests for data event charge breakdown."""

    @pytest.mark.asyncio
    async def test_data_event_breakdown(self, seeded_db: dict) -> None:
        """Query should format data volume correctly in MB."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]

        # Insert a data CDR event
        data_cdr_id = uuid.uuid7()
        await conn.execute(
            """INSERT INTO billing_cdr_events
               (id, session_id, subscriber_id, cdr_type, telecom_circle, cost_paise, status,
                start_time, end_time, volume_mb)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                data_cdr_id,
                uuid.uuid7(),
                subscriber_id,
                "data",
                "KA",
                155,  # charge_paise for 15.5MB at 10 paise/MB
                "rated",
                psycopg.Transaction.now() - psycopg.Interval(minutes=30),
                psycopg.Transaction.now() - psycopg.Interval(minutes=20),
                15.5,  # volume_mb
            ),
        )

        # Query charge breakdown
        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(data_cdr_id))

        # Verify data event formatting
        assert breakdown is not None
        assert breakdown["event_type"] == "data"
        assert "MB" in breakdown["duration_or_data"]
        assert "15.50" in breakdown["duration_or_data"]


class TestChargeBreakdownSMSEvent:
    """Integration tests for SMS event charge breakdown."""

    @pytest.mark.asyncio
    async def test_sms_event_breakdown(self, seeded_db: dict) -> None:
        """Query should format SMS as '1 SMS'."""
        from db.billing.queries import get_charge_breakdown

        conn = seeded_db["conn"]
        subscriber_id = seeded_db["subscriber_id"]

        # Insert an SMS CDR event
        sms_cdr_id = uuid.uuid7()
        await conn.execute(
            """INSERT INTO billing_cdr_events
               (id, session_id, subscriber_id, cdr_type, telecom_circle, cost_paise, status,
                start_time, end_time, to_number)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                sms_cdr_id,
                uuid.uuid7(),
                subscriber_id,
                "sms",
                "KA",
                100,  # charge_paise
                "rated",
                psycopg.Transaction.now() - psycopg.Interval(minutes=10),
                psycopg.Transaction.now() - psycopg.Interval(minutes=10),
                "1122334455",
            ),
        )

        # Query charge breakdown
        breakdown = await get_charge_breakdown(conn, str(subscriber_id), str(sms_cdr_id))

        # Verify SMS event formatting
        assert breakdown is not None
        assert breakdown["event_type"] == "sms"
        assert breakdown["duration_or_data"] == "1 SMS"


# Import at module level to avoid dependency issues
from testcontainers.postgres import PostgresContainer
