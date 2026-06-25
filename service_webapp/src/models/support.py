"""Pydantic request/response models for support tickets (Story 5.8).

The V1 ``support_tickets`` table is a generic ticketing schema; a billing dispute
raised via the chatbot is stored with ``category = 'billing_dispute'`` and the
dispute-specific values serialised into ``description`` (see
:mod:`db.support.commands`). These models describe the *public API contract*
(AC #2, #3, #4), not the storage shape. Money is integer paise internally;
INR conversion happens only at the presentation boundary (§1.11.2).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003  # pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field


class TicketCreateRequest(BaseModel):
    """Request body for POST /api/v1/support/tickets (AC #2)."""

    model_config = ConfigDict(extra="forbid")

    subscriber_id: UUID = Field(..., description="Subscriber raising the dispute (must match the JWT sub).")
    cdr_reference: str = Field(..., min_length=1, max_length=200, description="Disputed CDR event UUID.")
    charge_paise: int = Field(..., ge=0, description="Disputed charge amount in paise.")
    dispute_reason: str = Field(
        "subscriber_initiated",
        max_length=200,
        description="Reason code for the dispute (defaults to subscriber_initiated).",
    )


class TicketCreateResponse(BaseModel):
    """Response body for POST /api/v1/support/tickets (AC #2, #3)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID = Field(..., description="Created support ticket UUID (UUIDv7).")
    status: str = Field(..., description="Initial ticket status ('open').")
    created_at: datetime = Field(..., description="Ticket creation timestamp (ISO-8601 UTC).")


class SupportTicketItem(BaseModel):
    """A single dispute ticket in the GET /tickets list (AC #4)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID = Field(..., description="Support ticket UUID.")
    cdr_reference: str = Field(..., description="Disputed CDR event UUID (decoded from the ticket description).")
    dispute_reason: str = Field(..., description="Dispute reason code.")
    status: str = Field(..., description="Ticket status.")
    created_at: datetime = Field(..., description="Ticket creation timestamp (ISO-8601 UTC).")


__all__ = ["SupportTicketItem", "TicketCreateRequest", "TicketCreateResponse"]
