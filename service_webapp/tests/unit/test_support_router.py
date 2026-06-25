"""Unit tests for the support tickets router (Story 5.8 Task 1; AC #2, #3, #4).

Endpoints:
- POST /api/v1/support/tickets — create a billing-dispute ticket
- GET  /api/v1/support/tickets — list the subscriber's tickets
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_SUB_A = uuid4()
_CDR = "cdr-aaaaaaaa-bbbb-4321-cccc-1234567890ab"
_NOW = datetime.now(UTC)
_DESCRIPTION = (
    '{"cdr_reference": "cdr-aaaaaaaa-bbbb-4321-cccc-1234567890ab", '
    '"charge_paise": 1500, "dispute_reason": "subscriber_initiated"}'
)
# RETURNING columns: id, subscriber_id, category, subject, description, status, created_at
_INSERT_ROW: tuple = (uuid4(), str(_SUB_A), "billing_dispute", "Disputed charge", _DESCRIPTION, "open", _NOW)


def _sub_payload(sub_id: UUID = _SUB_A, groups: list[str] | None = None) -> dict:
    return {"sub": str(sub_id), "cognito:groups": groups or ["subscriber"], "phone_number": "919876543210"}


# ── Fakes ──────────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, *, row: tuple | None = None, rows: list[tuple] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    async def fetchone(self) -> tuple | None:
        return self._row

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    """Routes INSERT/SELECT on support_tickets to scripted results; records SQL."""

    def __init__(self, *, insert_row: tuple | None, select_rows: list[tuple]) -> None:
        self._insert_row = insert_row
        self._select_rows = select_rows
        self.last_sql: str = ""

    async def execute(self, sql: str, params: object = None):
        self.last_sql = sql
        lowered = sql.lower()
        if "insert into support_tickets" in lowered:
            return _FakeCursor(row=self._insert_row)
        if "from support_tickets" in lowered and "select" in lowered:
            return _FakeCursor(rows=self._select_rows)
        return _FakeCursor()


class _FakeDb:
    def __init__(
        self,
        *,
        insert_row: tuple | None = _INSERT_ROW,
        select_rows: list[tuple] | None = None,
    ) -> None:
        self._insert_row = insert_row
        self._select_rows = select_rows or []
        self.conn: _FakeConn | None = None

    @asynccontextmanager
    async def transaction(self):
        self.conn = _FakeConn(insert_row=self._insert_row, select_rows=self._select_rows)
        yield self.conn

    async def ping(self) -> bool:
        return True


def _make_app(
    *,
    db: _FakeDb | None = None,
    jwt_payload: dict | None = None,
    jwt_fail: str | None = None,
):
    from main import create_app

    return create_app(
        db_adapter=db or _FakeDb(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload(), fail=jwt_fail),
    )


# ── POST /tickets ─────────────────────────────────────────────────────────────


class TestCreateTicket:
    @pytest.mark.asyncio
    async def test_create_returns_201_with_ticket_id_and_open_status(self) -> None:
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/support/tickets",
                headers={"Authorization": "Bearer tok"},
                json={
                    "subscriber_id": str(_SUB_A),
                    "cdr_reference": _CDR,
                    "charge_paise": 1500,
                },
            )
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["status"] == "open"
        assert data["ticket_id"] == str(_INSERT_ROW[0])
        assert data["created_at"] is not None

    @pytest.mark.asyncio
    async def test_create_rejects_idor_mismatched_subscriber(self) -> None:
        """Body subscriber_id != JWT sub -> 403 (cannot file a ticket for another subscriber)."""
        other = uuid4()
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/support/tickets",
                headers={"Authorization": "Bearer tok"},
                json={
                    "subscriber_id": str(other),
                    "cdr_reference": _CDR,
                    "charge_paise": 1500,
                },
            )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_create_no_token_401(self) -> None:
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/support/tickets",
                json={"subscriber_id": str(_SUB_A), "cdr_reference": _CDR, "charge_paise": 1500},
            )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_create_wrong_role_403(self) -> None:
        app = _make_app(jwt_payload=_sub_payload(groups=["admin"]))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/support/tickets",
                headers={"Authorization": "Bearer tok"},
                json={"subscriber_id": str(_SUB_A), "cdr_reference": _CDR, "charge_paise": 1500},
            )
        assert r.status_code == 403


# ── GET /tickets ──────────────────────────────────────────────────────────────


class TestListTickets:
    @pytest.mark.asyncio
    async def test_list_returns_decoded_dispute_shape(self) -> None:
        # SELECT columns: id, description, status, created_at
        select_rows = [(uuid4(), _DESCRIPTION, "open", _NOW)]
        app = _make_app(db=_FakeDb(select_rows=select_rows))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/v1/support/tickets", headers={"Authorization": "Bearer tok"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["cdr_reference"] == _CDR
        assert data[0]["dispute_reason"] == "subscriber_initiated"
        assert data[0]["status"] == "open"

    @pytest.mark.asyncio
    async def test_status_filter_appends_case_insensitive_clause(self) -> None:
        db = _FakeDb(select_rows=[(uuid4(), _DESCRIPTION, "open", _NOW)])
        app = _make_app(db=db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get(
                "/api/v1/support/tickets?status=OPEN",
                headers={"Authorization": "Bearer tok"},
            )
        assert r.status_code == 200
        assert db.conn is not None
        assert "lower(status)" in db.conn.last_sql.lower()

    @pytest.mark.asyncio
    async def test_list_no_token_401(self) -> None:
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/v1/support/tickets")
        assert r.status_code == 401
