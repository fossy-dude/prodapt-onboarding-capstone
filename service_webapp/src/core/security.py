"""PII security helpers (Story 1.6; architecture §1.8.2, §1.11.6).

This module owns two distinct PII concerns:

1. **PII hygiene (§1.11.6, NFR-16, ARCH-32)** — raw MSISDN / name / address must
   never reach logs or OTEL span attributes. :func:`mask_msisdn` exposes only the
   last 4 digits; everywhere else the subscriber UUID is used.

2. **Consumption / sharing encryption (user decision 2026-06-20)** — PII is **not**
   encrypted at rest in a DB column; instead it is protected with AES-256-GCM when
   it leaves the trusted DB boundary (API responses, audit payloads, cross-service
   sharing). :class:`PiiCipher` is that primitive, keyed off
   ``settings.encryption_key``. The registration flow (Story 1.6) returns no PII,
   so the cipher is foundational here and is consumed by the profile/sharing
   stories (1.9+); it is unit-tested directly.

The TRAI CAF audit row stores a one-way SHA-256 hash of the canonicalised CAF
payload (:func:`canonical_caf_hash`) — tamper-evidence without duplicating PII
into the audit stream (AC #4, FR-3/FR-65).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from typing import Any

from core.config import settings


def mask_msisdn(msisdn: str) -> str:
    """Return a log/span-safe MSISDN view: the last 4 digits only (§1.11.6).

    ``msisdn[-4:]`` per the PII-hygiene rules. Short inputs are fully masked so a
    truncated/partial number is never echoed back in a diagnostic.
    """
    digits = "".join(ch for ch in msisdn if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


_MSISDN_DIGITS_RE = re.compile(r"^\+?\d{10,15}$")
_REGISTRATION_ID_RE = re.compile(r"^REG-\d{8}-[0-9a-fA-F]{8}$")


def normalize_login_identifier(raw: str) -> str:
    """Canonicalize a login identifier before it reaches Cognito.

    - Registration IDs and plain usernames (e.g. ``admin``) pass through unchanged.
    - Phone-like input is reduced to bare national digits: strip ``+``, spaces, dashes;
      drop a leading India country-code ``91`` (when >10 digits remain) or a trunk ``0``.
    """
    s = (raw or "").strip()
    if _REGISTRATION_ID_RE.match(s):
        return s
    if _MSISDN_DIGITS_RE.match(s):
        digits = re.sub(r"\D", "", s)
        if len(digits) > 10 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) > 10 and digits.startswith("0"):
            digits = digits[1:]
        return digits
    return s


def sha256_hex(data: str | bytes) -> str:
    """Hex SHA-256 digest of ``data`` (strings encoded as UTF-8)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_caf_hash(caf_payload: dict[str, Any]) -> str:
    """SHA-256 of the canonicalised CAF payload (deterministic JSON).

    Canonicalisation (sorted keys, no whitespace, non-ASCII escaped) makes the hash
    reproducible across runs and language boundaries — required for tamper-evidence.
    """
    canonical = json.dumps(caf_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_hex(canonical)


@lru_cache(maxsize=1)
def _get_cipher() -> PiiCipher:
    """Lazily build the singleton :class:`PiiCipher` from ``settings``.

    Cached so the key-derivation cost is paid once. Raises if no key is configured
    — callers that share PII must ensure ``ENCRYPTION_KEY`` is set; the registration
    flow does not share PII, so the service still boots without it.
    """
    return PiiCipher(settings.encryption_key)


class PiiCipher:
    """AES-256-GCM symmetric cipher for PII consumed/shared outside the DB.

    The 32-byte hex key is stretched through a salted PBKDF2 (SHA-256) so a
    short/shared key still yields a strong 256-bit AES key. Ciphertext is returned
    as ``urlsafe-base64(nonce || ciphertext || tag)`` — self-describing and safe to
    store in JSON / transport over HTTP.
    """

    _PBKDF2_ITERATIONS = 200_000
    _SALT = b"sboai-pii-v1"  # versioned; rotate key+version together if needed

    def __init__(self, key_material: str) -> None:
        if not key_material:
            raise ValueError("ENCRYPTION_KEY is not configured — PII sharing requires it.")
        # cryptography is only imported when the cipher is actually used (lazy), so
        # the boot path and unit tests that never instantiate PiiCipher do not
        # require the dependency.
        from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: PLC0415

        self._aes_key = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._SALT,
            iterations=self._PBKDF2_ITERATIONS,
        ).derive(key_material.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        """Encrypt ``plaintext`` → ``urlsafe-base64(nonce || ct || tag)``."""
        import base64  # noqa: PLC0415

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        nonce = os.urandom(12)  # unique per call — AES-GCM nonce reuse is catastrophic
        ct = AESGCM(self._aes_key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
        return base64.urlsafe_b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Decrypt a token produced by :meth:`encrypt`."""
        import base64  # noqa: PLC0415

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(self._aes_key).decrypt(nonce, ct, associated_data=None).decode("utf-8")


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII value with the configured key (consumption/sharing)."""
    return _get_cipher().encrypt(plaintext)


def decrypt_pii(token: str) -> str:
    """Decrypt a PII value produced by :func:`encrypt_pii`."""
    return _get_cipher().decrypt(token)


__all__ = [
    "PiiCipher",
    "canonical_caf_hash",
    "decrypt_pii",
    "encrypt_pii",
    "mask_msisdn",
    "normalize_login_identifier",
    "sha256_hex",
]
