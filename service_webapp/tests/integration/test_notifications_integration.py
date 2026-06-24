"""Integration tests for notifications (Story 4.2 Task 6).

Tests real DB operations with testcontainers Postgres:
- Real upsert + read cycle for preferences
- Real insert into notifications_events with status='simulated'
"""

from __future__ import annotations

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.mark.slow
class TestNotificationsIntegration:
    """Integration tests with real Postgres (testcontainers)."""

    @pytest.mark.asyncio
    async def test_upsert_and_read_preferences_cycle(self):
        """Test full upsert and read cycle with real database."""
        from uuid import uuid4

        postgres = PostgresContainer("postgres:16-alpine")
        postgres.start()

        try:
            # Setup connection
            import psycopg

            from adapters.postgres import conninfo_from

            conn_str = postgres.get_connection_url()
            conn_info = conninfo_from(conn_str)

            async with await psycopg.AsyncConnection.connect(conn_info) as conn:
                # Create tables
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS identity_subscribers (
                        id UUID PRIMARY KEY,
                        msisdn VARCHAR(15) NOT NULL
                    );
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS notifications_preferences (
                        id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                        subscriber_id UUID NOT NULL REFERENCES identity_subscribers(id),
                        notification_type VARCHAR(50) NOT NULL,
                        channel VARCHAR(20) NOT NULL,
                        is_enabled BOOL NOT NULL DEFAULT TRUE,
                        UNIQUE (subscriber_id, notification_type, channel)
                    );
                """)

                # Insert a subscriber
                subscriber_id = uuid4()
                await conn.execute(
                    "INSERT INTO identity_subscribers (id, msisdn) VALUES (%s, %s)",
                    subscriber_id,
                    "919876543210",
                )

                # Test upsert
                from db.notifications.commands import upsert_preference

                await upsert_preference(conn, str(subscriber_id), "LOW_BALANCE", True, "push")

                # Verify with read
                from db.notifications.queries import get_preferences

                prefs = await get_preferences(conn, str(subscriber_id))

                assert len(prefs) == 1
                assert prefs[0]["notification_type"] == "LOW_BALANCE"
                assert prefs[0]["is_enabled"] is True

                # Test update
                await upsert_preference(conn, str(subscriber_id), "LOW_BALANCE", False, "push")

                prefs = await get_preferences(conn, str(subscriber_id))
                assert prefs[0]["is_enabled"] is False

        finally:
            postgres.stop()

    @pytest.mark.asyncio
    async def test_insert_notification_event_with_simulated_status(self):
        """Test real insert into notifications_events with status='simulated'."""
        from uuid import uuid4

        postgres = PostgresContainer("postgres:16-alpine")
        postgres.start()

        try:
            import psycopg

            from adapters.postgres import conninfo_from

            conn_str = postgres.get_connection_url()
            conn_info = conninfo_from(conn_str)

            async with await psycopg.AsyncConnection.connect(conn_info) as conn:
                # Create tables
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS identity_subscribers (
                        id UUID PRIMARY KEY,
                        msisdn VARCHAR(15) NOT NULL
                    );
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS notifications_events (
                        id UUID DEFAULT uuid_generate_v7() PRIMARY KEY,
                        subscriber_id UUID NOT NULL REFERENCES identity_subscribers(id),
                        notification_type VARCHAR(50) NOT NULL,
                        channel VARCHAR(20) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        payload JSONB,
                        sent_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)

                # Insert a subscriber
                subscriber_id = uuid4()
                await conn.execute(
                    "INSERT INTO identity_subscribers (id, msisdn) VALUES (%s, %s)",
                    subscriber_id,
                    "919876543210",
                )

                # Test insert notification event
                from db.notifications.commands import insert_notification_event

                trace_id = str(uuid4())
                payload = {"balance_paise": 1000, "threshold_paise": 5000}

                await insert_notification_event(
                    conn,
                    str(subscriber_id),
                    "LOW_BALANCE",
                    "push",
                    payload,
                    trace_id,
                )

                # Verify insert
                cursor = await conn.execute(
                    "SELECT notification_type, channel, status, payload, sent_at FROM notifications_events WHERE subscriber_id = %s",
                    subscriber_id,
                )
                row = await cursor.fetchone()

                assert row is not None
                assert row[0] == "LOW_BALANCE"  # notification_type
                assert row[1] == "push"  # channel
                assert row[2] == "simulated"  # status
                assert row[3]["balance_paise"] == 1000  # payload
                assert row[4] is not None  # sent_at

        finally:
            postgres.stop()
