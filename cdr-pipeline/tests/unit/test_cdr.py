"""Unit tests for the CDR payload schema (Story 2.1, AC #3).

The discriminated union (``CdrEvent``) is the schema Story 2.2 validates the
``cdr.raw`` envelope payload against, so these tests pin its contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from models.cdr import CdrEvent, DataCdr, SmsCdr, VoiceCdr

_ADAPTER = TypeAdapter(CdrEvent)

_SUBSCRIBER = UUID("0192a4d0-1234-7000-8000-000000000abc")
_SESSION = UUID("0192a4d0-abcd-7000-8000-000000000def")
_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _voice() -> dict:
    return {
        "session_id": str(_SESSION),
        "subscriber_id": str(_SUBSCRIBER),
        "cdr_type": "voice",
        "telecom_circle": "TN",
        "cell_tower_id": "TWR-1",
        "roaming": False,
        "cost_paise": 3500,
        "start_time": _START.isoformat(),
        "end_time": datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC).isoformat(),
        "from_number": "919999900001",
        "to_number": "918888800002",
        "call_direction": "MO",
        "duration_seconds": 30,
        "call_status": "answered",
    }


def _sms() -> dict:
    return {
        "session_id": str(_SESSION),
        "subscriber_id": str(_SUBSCRIBER),
        "cdr_type": "sms",
        "telecom_circle": "KA",
        "cost_paise": 25,
        "start_time": _START.isoformat(),
        "message_direction": "MT",
        "sms_status": "delivered",
    }


def _data() -> dict:
    return {
        "session_id": str(_SESSION),
        "subscriber_id": str(_SUBSCRIBER),
        "cdr_type": "data",
        "telecom_circle": "DL",
        "cost_paise": 100,
        "start_time": _START.isoformat(),
        "network_type": "4G",
        "downloaded_mb": 12.5,
        "uploaded_mb": 1.25,
        "volume_mb": 13.75,
        "apn": "internet",
        "imei": "490154203237518",
        "operator_id": "OP-1",
    }


# ── Discriminator routing ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_voice(), VoiceCdr),
        (_sms(), SmsCdr),
        (_data(), DataCdr),
    ],
)
def test_discriminator_routes_to_variant(payload: dict, expected: type) -> None:
    cdr = _ADAPTER.validate_python(payload)
    assert isinstance(cdr, expected)


def test_invalid_cdr_type_rejected() -> None:
    payload = _voice()
    payload["cdr_type"] = "video"
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


# ── Type constraints called out by AC #3 ───────────────────────────────────────


def test_cost_paise_typed_as_int() -> None:
    cdr = _ADAPTER.validate_python(_voice())
    assert isinstance(cdr.cost_paise, int)
    assert cdr.cost_paise == 3500


def test_msisdns_are_strings() -> None:
    cdr = _ADAPTER.validate_python(_voice())
    assert isinstance(cdr, VoiceCdr)
    assert cdr.from_number == "919999900001"
    assert cdr.to_number == "918888800002"
    assert isinstance(cdr.from_number, str)
    assert isinstance(cdr.to_number, str)


@pytest.mark.parametrize("bad_status", ["MOBILE", "xx", "mo"])
def test_call_direction_enum_enforced(bad_status: str) -> None:
    payload = _voice()
    payload["call_direction"] = bad_status
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


@pytest.mark.parametrize("bad_network", ["6G", "lte", "5g"])
def test_network_type_enum_enforced(bad_network: str) -> None:
    payload = _data()
    payload["network_type"] = bad_network
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


# ── Variant-specific required fields ───────────────────────────────────────────


def test_voice_requires_voice_fields() -> None:
    """A voice CDR missing duration_seconds must fail validation."""
    payload = _voice()
    payload.pop("duration_seconds")
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


def test_extra_field_rejected() -> None:
    """Strict payload: unknown keys must not silently pass through to 2.2."""
    payload = _voice()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


def test_core_required_fields() -> None:
    payload = _sms()
    payload.pop("cost_paise")
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


# ── JSON round-trip ────────────────────────────────────────────────────────────


def test_voice_round_trip_json() -> None:
    cdr = _ADAPTER.validate_python(_voice())
    restored = _ADAPTER.validate_json(cdr.model_dump_json())
    assert restored == cdr
