"""Unit tests for Registration ID generation (AC #2)."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from services.registration import generate_registration_id

_REG_ID_RE = re.compile(r"^REG-\d{8}-[0-9a-f]{8}$")


def test_registration_id_format() -> None:
    """``REG-{YYYYMMDD}-{8 lowercase hex}`` (AC #2)."""
    reg_id = generate_registration_id(datetime(2026, 6, 20, 10, 30))
    assert _REG_ID_RE.match(reg_id)
    assert reg_id.startswith("REG-20260620-")


def test_registration_id_uses_pinned_date() -> None:
    reg_id = generate_registration_id(datetime(2025, 1, 2, 0, 0))
    assert reg_id.startswith("REG-20250102-")


def test_registration_id_random_half_is_unique_across_calls() -> None:
    """Collision resistance of the 4-random-byte half within a day."""
    ids = {generate_registration_id(datetime(2026, 6, 20, 12)) for _ in range(500)}
    # Astronomically unlikely to collide; assert we got many distinct values.
    assert len(ids) > 490


@pytest.mark.parametrize("reg_id", ["REG-20260620-a3f9c1d2", "REG-19700101-00000000", "REG-20261231-deadbeef"])
def test_registration_id_examples_match_pattern(reg_id: str) -> None:
    assert _REG_ID_RE.match(reg_id)
