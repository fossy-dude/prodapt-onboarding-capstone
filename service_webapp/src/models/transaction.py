"""Pydantic response model for a billing_transactions ledger row (Story 3.3).

``billing_transactions`` is an append-only ledger (V1:218-230). Each item is one
charge / recharge / refund. ``cdr_reference`` is not a column — it is derived by
the endpoint from ``reference_id`` where ``reference_type = 'cdr'``.

``transaction_type`` is stored as the raw writer value (e.g. ``cdr_deduction``
from the cdr-pipeline deduction writer, Story 2-3). The read boundary maps the
raw value to a canonical category (``charge | recharge | refund``, AC #1) via
:func:`canonical_transaction_type`, so the API exposes the documented categories
regardless of how each writer labels its rows.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003 — pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field

# Canonical transaction categories exposed by the API (AC #1). The ledger stores
# raw writer-specific values; the read boundary maps them here so the API is
# stable regardless of how each writer labels its rows. Unknown raw values pass
# through unchanged (the caller logs them) rather than being silently re-labelled.
TRANSACTION_TYPE_CANONICAL: dict[str, str] = {
    "cdr_deduction": "charge",
    "charge": "charge",
    "recharge": "recharge",
    "refund": "refund",
}


def canonical_transaction_type(raw: str) -> str:
    """Map a raw stored writer value to its canonical category (AC #1)."""
    return TRANSACTION_TYPE_CANONICAL.get(raw, raw)


class TransactionItem(BaseModel):
    """One row of the subscriber transaction ledger."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    transaction_type: str = Field(
        ...,
        description="Canonical category: 'charge' | 'recharge' | 'refund' (AC #1).",
    )
    amount_paise: int
    balance_after_paise: int
    cdr_reference: str | None = Field(
        default=None,
        description="reference_id where reference_type='cdr', else null.",
    )
    description: str | None = None
    created_at: datetime


__all__ = ["TRANSACTION_TYPE_CANONICAL", "TransactionItem", "canonical_transaction_type"]
