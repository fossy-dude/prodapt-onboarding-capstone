"""Unit tests for PII security helpers (AC #3, #4, #9; §1.11.6).

Covers MSISDN masking, the CAF SHA-256 hash (deterministic + never the raw payload),
and the application-layer PiiCipher round-trip (consumption/sharing encryption).
"""

from __future__ import annotations

import pytest

from core.security import (
    PiiCipher,
    canonical_caf_hash,
    mask_msisdn,
    sha256_hex,
)


@pytest.mark.parametrize(
    ("msisdn", "expected"),
    [
        ("9876543210", "***3210"),
        ("+919876543210", "***3210"),
        ("123", "***"),  # too short → fully masked
        ("", "***"),
    ],
)
def test_mask_msisdn_never_leaks_raw(msisdn: str, expected: str) -> None:
    assert mask_msisdn(msisdn) == expected
    if any(ch.isdigit() for ch in msisdn) and len([c for c in msisdn if c.isdigit()]) >= 4:
        # The raw full number must not survive masking.
        assert msisdn not in mask_msisdn(msisdn)


def test_sha256_hex_is_stable_and_hex() -> None:
    assert sha256_hex("abc") == sha256_hex("abc")
    assert len(sha256_hex("abc")) == 64
    assert all(c in "0123456789abcdef" for c in sha256_hex("abc"))


def test_canonical_caf_hash_is_deterministic_and_order_independent() -> None:
    payload = {"msisdn": "9876543210", "name": "Priya", "consent": True}

    # Same content, different insertion order → same hash (canonical JSON sorts keys).
    assert canonical_caf_hash(payload) == canonical_caf_hash({"name": "Priya", "msisdn": "9876543210", "consent": True})

    # The hash never contains the raw CAF PII.
    digest = canonical_caf_hash(payload)
    assert "9876543210" not in digest
    assert "Priya" not in digest


def test_canonical_caf_hash_changes_when_pii_changes() -> None:
    """Tamper-evidence: a changed field changes the hash (FR-3/FR-65)."""
    base = {"msisdn": "9876543210", "name": "Priya"}
    tampered = {"msisdn": "9876543210", "name": "Priya "}
    assert canonical_caf_hash(base) != canonical_caf_hash(tampered)


_TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def test_pii_cipher_round_trip() -> None:
    cipher = PiiCipher(_TEST_KEY)
    token = cipher.encrypt("9876543210")
    # Ciphertext is opaque — never the plaintext.
    assert "9876543210" not in token
    assert cipher.decrypt(token) == "9876543210"


def test_pii_cipher_requires_key() -> None:
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        PiiCipher("")
