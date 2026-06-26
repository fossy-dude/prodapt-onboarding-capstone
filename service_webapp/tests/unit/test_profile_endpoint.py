"""Unit tests for the profile management endpoints (Story 1.9 AC #1-#7).

GET/PATCH ``/api/v1/subscriber/profile`` are exercised through the ASGI app with an
in-memory :class:`FakeProfileDb` (mimics ``DatabaseProtocol.transaction()``) and
:class:`~core.auth.FakeJWTValidator` injected via ``create_app``. No database or AWS
dependency. The fake records every executed statement + params so the tests can
assert the audit INSERT, owner-derived targeting, and absence of PII in logs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from core.auth import FakeJWTValidator

if TYPE_CHECKING:
    import pytest

_SUB_A = "11111111-1111-4111-8111-111111111111"
_SUB_B = "22222222-2222-4222-8222-222222222222"
_MSISDN_A = "919876543210"
_MSISDN_B = "919876543211"

# Profile SELECT column order (see _PROFILE_SELECT in routers/account.py):
# (subscriber_name, email, address_line1, address_line2, city, state, pin_code, kyc_status).
_ROW_A = ("Priya Sharma", "priya@example.com", "12 MG Road", "Flat 3", "Bengaluru", "Karnataka", "560001", "verified")
_ROW_B = ("Arun Gupta", "arun@example.com", "9 Park St", "", "Mumbai", "Maharashtra", "400001", "rejected")


class _FakeCursor:
    """Mimics the psycopg3 cursor subset used by the handlers."""

    def __init__(self, *, row: tuple | None = None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Routes execute() to a scripted result based on the SQL verb."""

    def __init__(self, state: FakeProfileDb) -> None:
        self._state = state

    async def execute(self, sql: str, params: tuple | None = None):
        lowered = sql.lstrip().lower()
        self._state.calls.append((lowered, params))
        # Check if this is a subscriber lookup for resolve_subscriber_id
        # (it queries identity_subscribers with an msisdn IN clause and returns only id)
        if (
            "identity_subscribers" in lowered
            and "msisdn" in lowered
            and "where" in lowered
            and "id" in lowered
            and "from" in lowered
        ):
            # This is the resolve_subscriber_id lookup - return the subscriber UUID based on MSISDN
            # If any of the params contain _MSISDN_B, return _SUB_B; otherwise return _SUB_A
            if params and len(params) > 0:
                for param in params:
                    if _MSISDN_B in str(param):
                        return _FakeCursor(row=(_SUB_B,))
            return _FakeCursor(row=(_SUB_A,))
        # Check if this is the profile SELECT (has lateral join for kyc_records)
        if "lateral" in lowered and "identity_kyc_records" in lowered:
            # This is the profile SELECT
            return _FakeCursor(row=self._state.select_row)
        if lowered.startswith("select") and "identity_subscribers" not in lowered:
            # This is another profile SELECT (fallback)
            return _FakeCursor(row=self._state.select_row)
        if lowered.startswith("update"):
            return _FakeCursor(rowcount=self._state.update_rowcount)
        if lowered.startswith("insert"):
            self._state.inserts.append((lowered, params))
            return _FakeCursor(rowcount=1)
        return _FakeCursor()


class FakeProfileDb:
    """In-memory stand-in for the psycopg3 adapter used by the profile endpoints."""

    def __init__(self, *, select_row: tuple | None = _ROW_A, update_rowcount: int = 1) -> None:
        self.select_row = select_row
        self.update_rowcount = update_rowcount
        self.calls: list[tuple[str, tuple | None]] = []
        self.inserts: list[tuple[str, tuple | None]] = []

    @asynccontextmanager
    async def transaction(self):
        yield _FakeConn(self)

    async def ping(self) -> bool:
        return True


def _make_app(
    *,
    sub: str | None = _SUB_A,
    msisdn: str = _MSISDN_A,
    groups: tuple[str, ...] = ("subscriber",),
    select_row: tuple | None = _ROW_A,
    update_rowcount: int = 1,
):
    """Build an app wired to a FakeProfileDb + FakeJWTValidator; return (app, db)."""
    from main import create_app

    payload: dict = {"cognito:groups": list(groups)}
    if sub is not None:
        payload["sub"] = sub
    payload["phone_number"] = msisdn
    db = FakeProfileDb(select_row=select_row, update_rowcount=update_rowcount)
    app = create_app(db_adapter=db, jwt_validator=FakeJWTValidator(payload=payload))
    return app, db


_AUTH = {"Authorization": "Bearer test-token"}


async def _get(
    sub: str = _SUB_A, msisdn: str = _MSISDN_A, *, groups: tuple[str, ...] = ("subscriber",), select_row=_ROW_A
):
    app, db = _make_app(sub=sub, msisdn=msisdn, groups=groups, select_row=select_row)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/subscriber/profile", headers=_AUTH)
    return resp, db


async def _patch(
    body: dict, *, sub: str = _SUB_A, msisdn: str = _MSISDN_A, select_row=_ROW_A, update_rowcount: int = 1
):
    app, db = _make_app(sub=sub, msisdn=msisdn, select_row=select_row, update_rowcount=update_rowcount)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.patch("/api/v1/subscriber/profile", json=body, headers=_AUTH)
    return resp, db


# ── GET ───────────────────────────────────────────────────────────────────────


async def test_get_profile_returns_decrypted_profile_envelope() -> None:
    """AC #1, #4: GET returns decrypted name/email/address + kyc_status in the envelope."""
    resp, _ = await _get()

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert set(body["meta"]) == {"trace_id", "timestamp"}
    data = body["data"]
    assert data["name"] == "Priya Sharma"
    assert data["email"] == "priya@example.com"
    assert data["address"] == {
        "line1": "12 MG Road",
        "line2": "Flat 3",
        "city": "Bengaluru",
        "state": "Karnataka",
        "pin_code": "560001",
    }
    assert data["kyc_status"] == "verified"


async def test_get_profile_normalises_kyc_status_case_and_default() -> None:
    """AC #2: kyc_status is lowercased; NULL/empty defaults to 'pending'."""
    row = ("Priya Sharma", "priya@example.com", "12 MG Road", "", "Bengaluru", "Karnataka", "560001", None)
    resp, _ = await _get(select_row=row)
    assert resp.json()["data"]["kyc_status"] == "pending"

    row_pending = ("Priya Sharma", "priya@example.com", "12 MG Road", "", "Bengaluru", "Karnataka", "560001", "PENDING")
    resp, _ = await _get(select_row=row_pending)
    assert resp.json()["data"]["kyc_status"] == "pending"


async def test_get_profile_404_when_subscriber_missing() -> None:
    """No row for the JWT sub → 404 NOT_FOUND."""
    resp, _ = await _get(select_row=None)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_get_profile_403_wrong_role() -> None:
    """AC #6: a token without the subscriber role → 403 FORBIDDEN."""
    resp, _ = await _get(groups=("ops",))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_get_profile_401_when_phone_claim_missing() -> None:
    """A valid-shape token lacking 'phone_number' → 401 (resolver requires phone)."""
    app, _ = _make_app(sub=_SUB_A, msisdn="")  # Empty phone_number
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/subscriber/profile", headers=_AUTH)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_get_profile_targets_jwt_sub_owner_isolation() -> None:
    """AC #6: the SELECT is scoped to the JWT sub (owner-only by construction)."""
    resp_a, db_a = await _get(sub=_SUB_A, select_row=_ROW_A)
    assert resp_a.json()["data"]["email"] == "priya@example.com"
    select_calls = [c for c in db_a.calls if c[0].startswith("select") and "lateral" in c[0]]
    assert select_calls, "expected a profile SELECT with lateral join"
    # The WHERE id = %s::uuid param is the resolved subscriber UUID — never a client-supplied id.
    assert select_calls[0][1] == (_SUB_A,)

    # A different subscriber's token resolves their own record only.
    resp_b, _ = await _get(sub=_SUB_B, select_row=_ROW_B)
    assert resp_b.json()["data"]["email"] == "arun@example.com"
    assert resp_b.json()["data"]["kyc_status"] == "rejected"


# ── PATCH ─────────────────────────────────────────────────────────────────────


async def test_patch_profile_updates_and_writes_one_audit_row() -> None:
    """AC #3, #4: PATCH re-writes fields, appends exactly one UPDATE_PROFILE audit row, returns 200."""
    updated = (
        "Priya Sharma",
        "priya.new@example.com",
        "50 New Rd",
        "Flat 3",
        "Bengaluru",
        "Karnataka",
        "560011",
        "verified",
    )
    resp, db = await _patch(
        {"email": "priya.new@example.com", "address_line1": "50 New Rd", "pin_code": "560011"},
        select_row=updated,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == "priya.new@example.com"
    assert data["address"]["line1"] == "50 New Rd"
    assert data["address"]["pin_code"] == "560011"

    # Exactly one append-only audit INSERT carrying UPDATE_PROFILE.
    audit_inserts = [i for i in db.inserts if "billing_audit_log" in i[0]]
    assert len(audit_inserts) == 1
    sql, params = audit_inserts[0]
    assert "insert into billing_audit_log" in sql
    assert params[0] == "SUBSCRIBER_PROFILE"  # entity_type
    assert params[1] == _SUB_A  # entity_id (uuid)
    assert params[2] == "UPDATE_PROFILE"  # action
    assert params[3] == _SUB_A  # actor_id
    assert params[4] == "SUBSCRIBER"  # actor_type
    new_value = params[5]
    assert new_value.obj == {"fields_updated": ["address_line1", "email", "pin_code"]}


async def test_patch_profile_audit_carries_no_raw_pii() -> None:
    """AC #7/NFR-16: the audit new_value holds field names only — never raw PII."""
    resp, db = await _patch({"email": "secret.value@example.com", "city": "Pune"}, select_row=_ROW_A)
    assert resp.status_code == 200
    audit_inserts = [i for i in db.inserts if "billing_audit_log" in i[0]]
    assert audit_inserts
    new_value = audit_inserts[0][1][5]
    assert "secret.value@example.com" not in str(new_value)
    assert "Pune" not in str(new_value)
    assert new_value.obj == {"fields_updated": ["city", "email"]}


async def test_patch_profile_422_on_invalid_email() -> None:
    """AC #3: bad email → 422 VALIDATION_ERROR; no DB write attempted."""
    resp, db = await _patch({"email": "not-an-email"}, select_row=_ROW_A)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not db.inserts  # nothing persisted


async def test_patch_profile_422_on_empty_body() -> None:
    """An empty PATCH body → 422 (must provide at least one field)."""
    resp, db = await _patch({}, select_row=_ROW_A)
    assert resp.status_code == 422
    assert not db.inserts


async def test_patch_profile_422_on_unknown_field() -> None:
    """extra='forbid' → an unknown field is rejected as 422."""
    resp, _ = await _patch({"msisdn": "9876543210"}, select_row=_ROW_A)
    assert resp.status_code == 422


async def test_patch_profile_404_when_subscriber_missing() -> None:
    """UPDATE matched no row → 404; the transaction rolls back (no audit row)."""
    resp, db = await _patch({"city": "Pune"}, select_row=_ROW_A, update_rowcount=0)
    assert resp.status_code == 404
    assert not db.inserts  # rolled back — audit never written


async def test_patch_profile_targets_jwt_sub() -> None:
    """AC #6: the UPDATE + SELECT are scoped to the JWT sub (owner-only)."""
    resp, db = await _patch({"city": "Pune"}, sub=_SUB_B, msisdn=_MSISDN_B, select_row=_ROW_B)
    assert resp.status_code == 200
    update_calls = [c for c in db.calls if c[0].startswith("update")]
    assert update_calls
    # WHERE id = %s::uuid → last param is the JWT sub.
    assert update_calls[0][1][-1] == _SUB_B


# ── PII hygiene (AC #7) ───────────────────────────────────────────────────────


async def test_get_profile_logs_no_raw_pii(caplog: pytest.LogCaptureFixture) -> None:
    """AC #7: logs never carry raw name/email/address — only the subscriber UUID."""
    with caplog.at_level(logging.DEBUG, logger="routers.account"):
        await _get()
    text = caplog.text
    assert "Priya Sharma" not in text
    assert "priya@example.com" not in text
    assert "560001" not in text


async def test_patch_profile_logs_no_raw_pii(caplog: pytest.LogCaptureFixture) -> None:
    """AC #7: the PATCH log line carries sub + field names only, never values."""
    with caplog.at_level(logging.DEBUG, logger="routers.account"):
        await _patch({"email": "secret.value@example.com"}, select_row=_ROW_A)
    text = caplog.text
    assert "secret.value@example.com" not in text
    assert "email" in text  # field name is logged; the value is not
    assert _SUB_A in text  # the subscriber UUID is logged


async def test_profile_endpoints_are_uuid_stable() -> None:
    """Sanity: a random UUIDv4 sub flows through end-to-end without coercion errors."""
    rand_sub = str(uuid4())
    resp, _ = await _get(sub=rand_sub, select_row=_ROW_A)
    assert resp.status_code == 200


async def test_profile_endpoint_spans_no_raw_pii() -> None:
    """AC #7/NFR-16: GET profile OTEL span attributes never carry raw PII values."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    app, _ = _make_app(select_row=_ROW_A)
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/v1/subscriber/profile", headers=_AUTH)

    pii_values = ("Priya Sharma", "priya@example.com", "560001", "12 MG Road", "Bengaluru")
    for span in exporter.get_finished_spans():
        for attr_value in (span.attributes or {}).values():
            for pii in pii_values:
                assert pii not in str(attr_value), f"PII '{pii}' leaked into span {span.name}: {dict(span.attributes)}"
