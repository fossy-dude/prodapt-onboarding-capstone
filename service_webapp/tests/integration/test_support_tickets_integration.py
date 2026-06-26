"""Integration tests for support ticket creation (Story 5.8 Task 6; AC #2, #7).

Real Postgres (testcontainers) verifies that ``create_ticket`` inserts a row with
a server-generated UUIDv7 primary key, status ``open``, and that
``get_tickets_by_subscriber`` decodes the serialised dispute payload back.

``uuid_generate_v7()`` is the production ``pg_uuidv7`` extension; in the throwaway
testcontainer it is stubbed with ``gen_random_uuid()`` (the PK is still generated
server-side and is a valid UUID — true time-ordered UUIDv7 comes from pg_uuidv7 in
real deploys, per architecture §1.7.1).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.mark.slow
@pytest.mark.integration
class TestSupportTicketsIntegration:
    """Integration tests with real Postgres (testcontainers)."""

    @pytest.mark.asyncio
    async def test_create_ticket_generates_server_uuid_pk_and_open_status(self) -> None:
        postgres = PostgresContainer("postgres:16-alpine")
        postgres.start()
        try:
            import psycopg

            from adapters.postgres import conninfo_from

            conn_info = conninfo_from(postgres.get_connection_url())
            async with await psycopg.AsyncConnection.connect(conn_info) as conn:
                # Stub the production pg_uuidv7 extension function.
                await conn.execute(
                    "CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid "
                    "LANGUAGE sql AS $$ SELECT gen_random_uuid() $$",
                )
                await conn.execute(
                    """
                    CREATE TABLE identity_subscribers (
                        id UUID PRIMARY KEY,
                        msisdn VARCHAR(15) NOT NULL
                    );
                    """,
                )
                await conn.execute(
                    """
                    CREATE TABLE support_tickets (
                        id            UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
                        subscriber_id UUID NOT NULL REFERENCES identity_subscribers (id),
                        category      VARCHAR(50) NOT NULL,
                        subject       VARCHAR(200) NOT NULL,
                        description   TEXT NOT NULL,
                        status        VARCHAR(20) NOT NULL DEFAULT 'open',
                        priority      VARCHAR(10) NOT NULL DEFAULT 'medium',
                        assigned_to   VARCHAR(200),
                        resolved_at   TIMESTAMPTZ,
                        created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                        modified_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL
                    );
                    """,
                )

                subscriber_id = uuid4()
                await conn.execute(
                    "INSERT INTO identity_subscribers (id, msisdn) VALUES (%s, %s)",
                    (subscriber_id, "919876543210"),
                )

                from db.support.commands import create_ticket

                cdr_reference = "cdr-aaaaaaaa-bbbb-4321-cccc-1234567890ab"
                ticket = await create_ticket(
                    conn,
                    subscriber_id=str(subscriber_id),
                    cdr_reference=cdr_reference,
                    charge_paise=1500,
                    dispute_reason="subscriber_initiated",
                )

                # AC #7: server-generated UUID PK, status 'open' (V1 default, no migration).
                assert ticket["status"] == "open"
                pk = ticket["id"]
                assert isinstance(pk, UUID)
                assert pk.version is not None  # server-generated, valid UUID (pg_uuidv7 -> v7 in prod)

                # Round-trip: get_tickets_by_subscriber decodes the dispute payload (AC #4).
                from db.support.queries import get_tickets_by_subscriber

                rows = await get_tickets_by_subscriber(conn, subscriber_id=str(subscriber_id))
                assert len(rows) == 1
                assert rows[0]["status"] == "open"
                assert rows[0]["cdr_reference"] == cdr_reference
                assert rows[0]["dispute_reason"] == "subscriber_initiated"
                assert rows[0]["ticket_id"] == pk
        finally:
            postgres.stop()
