"""Unit tests for GET /api/v1/subscriber/transactions (Story 3.3 AC #1-#5).

The endpoint is exercised with FakeJWTValidator + an in-memory fake Postgres
adapter that scripts ``billing_transactions`` rows. No real infrastructure is
required. Cursor pagination, ``cdr_reference`` derivation, ordering and the auth
matrix are all covered here; the raw SQL is verified separately in the
integration suite (``tests/integration``, skipped by default).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

_SUB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SUB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_MSISDN = "919876543210"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    """Returns scripted ``billing_transactions`` rows; records executed params."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed_sql: str = ""
        self.executed_params: tuple = ()

    async def execute(self, sql: str, params=None):
        self.executed_sql = sql
        self.executed_params = tuple(params or ())
        return _FakeCursor(self._rows)


class FakeDb:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []
        self.conn: _FakeConn | None = None

    @asynccontextmanager
    async def transaction(self):
        self.conn = _FakeConn(self._rows)
        yield self.conn

    async def ping(self) -> bool:
        return True


def _row(
    *,
    txn_type: str = "cdr_deduction",
    amount: int = 500,
    balance_after: int = 49500,
    ref_type: str | None = "cdr",
    ref_id: UUID | None = None,
    description: str | None = "data charge",
    created_at: datetime | None = None,
) -> tuple:
    """8-column row matching the get_transactions_page SELECT order."""
    return (
        uuid4(),  # id (UUIDv7 in prod; plain uuid4 here)
        txn_type,
        amount,
        balance_after,
        ref_type,
        ref_id if ref_id is not None else uuid4(),
        description,
        created_at or _NOW,
    )


def _sub_payload(sub_id: str = _SUB_A, groups: list[str] | None = None) -> dict:
    return {"sub": sub_id, "cognito:groups": groups or ["subscriber"], "phone_number": _MSISDN}


def _make_app(*, db: FakeDb | None = None, jwt_payload: dict | None = None, jwt_fail: str | None = None):
    from main import create_app

    return create_app(
        db_adapter=db or FakeDb(),
        jwt_validator=FakeJWTValidator(payload=jwt_payload or _sub_payload(), fail=jwt_fail),
    )


# ── /transactions tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transactions_returns_items_with_required_fields():
    """AC #1: paginated ledger of transaction_type, amount, balance_after, cdr_reference, description, created_at."""
    cdr = uuid4()
    db = FakeDb(rows=[_row(txn_type="cdr_deduction", amount=500, balance_after=49500, ref_id=cdr)])
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    item = r.json()["data"][0]
    assert item["transaction_type"] == "cdr_deduction"
    assert item["amount_paise"] == 500
    assert item["balance_after_paise"] == 49500
    assert item["cdr_reference"] == str(cdr)
    assert item["description"] == "data charge"
    assert item["created_at"].startswith("2026-01-01")
    assert "id" in item


@pytest.mark.asyncio
async def test_transactions_desc_order_preserved():
    """AC #2: newest first (created_at DESC). The query orders; the endpoint must not reshuffle."""
    rows = [
        _row(created_at=_NOW + timedelta(minutes=10)),
        _row(created_at=_NOW + timedelta(minutes=5)),
        _row(created_at=_NOW),
    ]
    db = FakeDb(rows=rows)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    created = [i["created_at"] for i in r.json()["data"]]
    assert created == sorted(created, reverse=True)


@pytest.mark.asyncio
async def test_transactions_page_size_and_next_cursor():
    """AC #3: page_size respected; next_cursor = last id of page when more remain, else null."""
    rows = [_row() for _ in range(3)]  # 3 rows available
    db = FakeDb(rows=rows)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/subscriber/transactions?page_size=2",
            headers={"Authorization": "Bearer tok"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert body["meta"]["next_cursor"] == body["data"][1]["id"]


@pytest.mark.asyncio
async def test_transactions_next_cursor_null_when_exhausted():
    """AC #3: fewer rows than page_size → next_cursor null."""
    rows = [_row()]
    db = FakeDb(rows=rows)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/subscriber/transactions?page_size=20",
            headers={"Authorization": "Bearer tok"},
        )
    assert r.status_code == 200
    assert r.json()["meta"]["next_cursor"] is None


@pytest.mark.asyncio
async def test_transactions_empty_page_returns_null_cursor():
    """AC #3: no rows at all → empty data, next_cursor null."""
    db = FakeDb(rows=[])
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json()["data"] == []
    assert r.json()["meta"]["next_cursor"] is None


@pytest.mark.asyncio
async def test_transactions_cdr_reference_null_for_non_cdr():
    """AC #1/#4: non-CDR rows (reference_type != 'cdr') have cdr_reference null."""
    rows = [
        _row(txn_type="recharge", amount=10000, balance_after=10000, ref_type="recharge", ref_id=None),
        _row(txn_type="cdr_deduction", ref_type="cdr", ref_id=uuid4()),
    ]
    db = FakeDb(rows=rows)
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    items = r.json()["data"]
    by_type = {i["transaction_type"]: i for i in items}
    assert by_type["recharge"]["cdr_reference"] is None
    assert by_type["cdr_deduction"]["cdr_reference"] is not None


@pytest.mark.asyncio
async def test_transactions_cursor_param_forwarded_to_query():
    """AC #3: the cursor is forwarded into the query params (owner-scoped keyset paging)."""
    cursor = uuid4()
    db = FakeDb(rows=[])
    app = _make_app(db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get(
            f"/api/v1/subscriber/transactions?cursor={cursor}&page_size=5",
            headers={"Authorization": "Bearer tok"},
        )
    assert db.conn is not None
    assert str(cursor) in db.conn.executed_params


@pytest.mark.asyncio
async def test_transactions_scoped_to_jwt_sub():
    """Owner assertion: the subscriber_id bound into the query is the JWT ``sub`` (cross-sub isolation)."""
    db = FakeDb(rows=[])
    app = _make_app(db=db, jwt_payload=_sub_payload(sub_id=_SUB_A))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    assert db.conn is not None
    assert _SUB_A in db.conn.executed_params
    assert _SUB_B not in db.conn.executed_params


@pytest.mark.asyncio
async def test_transactions_no_token_401():
    """Auth matrix: missing token -> 401."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_transactions_wrong_role_403():
    """Auth matrix: valid token but wrong role -> 403."""
    app = _make_app(jwt_payload=_sub_payload(groups=["ops"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/subscriber/transactions", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
