"""Pydantic response model for a billing_transactions ledger row (Story 3.3).

``billing_transactions`` is an append-only ledger (V1:218-230). Each item is one
charge / recharge / refund. ``cdr_reference`` is not a column — it is derived by
the endpoint from ``reference_id`` where ``reference_type = 'cdr'``.

``transaction_type`` is the **raw stored writer value** (e.g. ``cdr_deduction``
from the cdr-pipeline deduction writer, Story 2-3). The reader returns it
verbatim so reader and writers always agree; the AC's ``CHARGE|RECHARGE|REFUND``
is the conceptual category, surfaced as a friendly label by the frontend.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003 — pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field


class TransactionItem(BaseModel):
    """One row of the subscriber transaction ledger."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    transaction_type: str = Field(
        ...,
        description="Raw stored writer value, e.g. 'cdr_deduction' (Story 3.3 variance).",
    )
    amount_paise: int
    balance_after_paise: int
    cdr_reference: str | None = Field(
        default=None,
        description="reference_id where reference_type='cdr', else null.",
    )
    description: str | None = None
    created_at: datetime


__all__ = ["TransactionItem"]
