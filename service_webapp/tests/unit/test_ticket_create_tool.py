"""Unit tests for the ticket_create Support Agent tool (Story 5.8 AC #1, #2, #3).

The tool ends the dispute multi-turn flow by inserting a billing-dispute ticket
and returning a ticket id + the 48-hour SLA message. The subscriber is resolved
from the identity context (never the LLM-supplied value).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agents.support.identity import support_context
from agents.support.tools import set_support_adapters, ticket_create

_SUB = uuid4()
_CDR = "cdr-12345678-abcd-4321-abcd-1234567890ab"
_NOW = datetime.now(UTC)
_DESCRIPTION = (
    '{"cdr_reference": "cdr-12345678-abcd-4321-abcd-1234567890ab", '
    '"charge_paise": 1500, "dispute_reason": "subscriber_initiated"}'
)
# RETURNING columns: id, subscriber_id, category, subject, description, status, created_at
_INSERT_ROW: tuple = (
    uuid4(),
    str(_SUB),
    "billing_dispute",
    "Disputed charge: CDR cdr-1",
    _DESCRIPTION,
    "open",
    _NOW,
)


class _FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Captures the INSERT params so tests can assert the resolved subscriber."""

    def __init__(self, row: tuple) -> None:
        self._row = row
        self.last_params: object = None

    async def execute(self, sql: str, params: object = None):
        self.last_params = params
        return _FakeCursor(self._row)


class _FakeDb:
    def __init__(self, row: tuple) -> None:
        self._row = row
        self.conn: _FakeConn | None = None

    @asynccontextmanager
    async def transaction(self):
        self.conn = _FakeConn(self._row)
        yield self.conn

    async def ping(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset_adapters() -> None:
    yield
    set_support_adapters(None, None)


class TestTicketCreateTool:
    @pytest.mark.asyncio
    async def test_returns_ticket_id_and_sla_message(self) -> None:
        db = _FakeDb(_INSERT_ROW)
        set_support_adapters(None, db)
        with support_context(subscriber_id=str(_SUB), msisdn=None, session_id="sess"):
            result = await ticket_create.ainvoke(
                {"subscriber_id": str(_SUB), "cdr_reference": _CDR, "charge_paise": 1500},
            )

        ticket_id = str(_INSERT_ROW[0])
        assert result["ticket_id"] == ticket_id
        assert result["status"] == "open"
        assert result["message"] == (f"Ticket #{ticket_id} has been created. Our team will review it within 48 hours.")

    @pytest.mark.asyncio
    async def test_uses_context_subscriber_not_llm_arg(self) -> None:
        db = _FakeDb(_INSERT_ROW)
        set_support_adapters(None, db)
        # Pass a *different* subscriber_id (the LLM-supplied value) — must be ignored.
        with support_context(subscriber_id=str(_SUB), msisdn=None, session_id="sess"):
            await ticket_create.ainvoke(
                {
                    "subscriber_id": "00000000-0000-7000-8000-111111111111",
                    "cdr_reference": _CDR,
                    "charge_paise": 1500,
                },
            )

        assert db.conn is not None
        # create_ticket INSERT params: (subscriber_id, subject, description) — first is the id.
        insert_params = db.conn.last_params
        assert isinstance(insert_params, tuple)
        assert insert_params[0] == str(_SUB)

    def test_ticket_create_registered_in_support_tools(self) -> None:
        from agents.support.tools import SUPPORT_TOOLS

        names = [t.name for t in SUPPORT_TOOLS]
        assert "ticket_create" in names
        assert "balance_lookup" in names
