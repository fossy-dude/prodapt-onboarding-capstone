"""Support-domain API endpoints (Story 5.8 dispute tickets, Story 5.9 recommendation feedback, Story 5.10 session-end).

- POST /api/v1/support/tickets             — create a billing-dispute ticket (Story 5.8)
- GET  /api/v1/support/tickets              — list the subscriber's tickets (Story 5.8)
- POST /api/v1/recommendations/feedback     — log Accept/Dismiss on a plan recommendation (Story 5.9)
- POST /api/v1/support/chat/end             — trigger Conclusion Agent on session end (Story 5.10)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.conclusion import get_conclusion_graph
from core.auth import require_role
from core.errors import DomainError, ForbiddenError
from core.responses import success_envelope
from db.support.commands import create_ticket, log_recommendation_feedback
from db.support.queries import get_tickets_by_subscriber
from models.support import SupportTicketItem, TicketCreateRequest, TicketCreateResponse
from routers._identity import resolve_subscriber_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["support"])


class FeedbackRequest(BaseModel):
    """Request body for plan recommendation feedback (Story 5.9)."""

    subscriber_id: UUID
    plan_id: UUID
    action: Literal["ACCEPTED", "DISMISSED"]


def _db(request: Request):
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "unknown")


@router.post("/api/v1/recommendations/feedback", status_code=201)
async def post_recommendation_feedback(
    body: FeedbackRequest,
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Record subscriber Accept/Dismiss feedback on a plan recommendation (AC #5, #6)."""
    db = _db(request)
    async with db.transaction() as conn:
        await log_recommendation_feedback(
            conn,
            subscriber_id=body.subscriber_id,
            plan_id=body.plan_id,
            action=body.action,
        )
    logger.info(
        "Recommendation feedback: subscriber=%s plan=%s action=%s",
        body.subscriber_id,
        body.plan_id,
        body.action,
    )
    return JSONResponse(
        status_code=201,
        content=success_envelope({"status": "recorded"}, trace_id=_trace_id(request)),
    )


# ── Story 5.8: billing-dispute support tickets ────────────────────────────────


@router.post("/api/v1/support/tickets", status_code=201)
async def create_support_ticket(
    request: Request,
    body: TicketCreateRequest,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Create a billing-dispute support ticket (AC #2, #3).

    The subscriber is resolved from the token's phone number (authoritative); a body
    ``subscriber_id`` that does not match is rejected (403) to prevent IDOR. The
    ticket is stored with ``category = 'billing_dispute'`` and the dispute values
    serialised into ``description`` — no migration (AC #7).
    """
    db = _db(request)
    async with db.transaction() as conn:
        subscriber_id = await resolve_subscriber_id(conn, jwt_payload)
        if body.subscriber_id != UUID(subscriber_id):
            raise ForbiddenError("Cannot create a ticket for a different subscriber.")
        ticket = await create_ticket(
            conn,
            subscriber_id=subscriber_id,
            cdr_reference=body.cdr_reference,
            charge_paise=body.charge_paise,
            dispute_reason=body.dispute_reason,
        )
    response = TicketCreateResponse(
        ticket_id=ticket["id"],
        status=ticket["status"],
        created_at=ticket["created_at"],
    )
    return JSONResponse(
        status_code=201,
        content=success_envelope(response.model_dump(mode="json"), trace_id=_trace_id(request)),
    )


@router.get("/api/v1/support/tickets", status_code=200)
async def list_support_tickets(
    request: Request,
    status: str | None = Query(default=None, description="Optional status filter, e.g. 'open'."),
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """List the subscriber's support tickets (AC #4).

    Returns the dispute shape (``ticket_id``, ``cdr_reference``,
    ``dispute_reason``, ``status``, ``created_at``); the dispute values are
    decoded from the ticket ``description``. ``status`` is matched
    case-insensitively, so ``OPEN`` matches the stored ``open``.
    """
    db = _db(request)
    async with db.transaction() as conn:
        subscriber_id = await resolve_subscriber_id(conn, jwt_payload)
        tickets = await get_tickets_by_subscriber(conn, subscriber_id=subscriber_id, status=status)
    items = [SupportTicketItem(**t) for t in tickets]
    return JSONResponse(
        status_code=200,
        content=success_envelope([i.model_dump(mode="json") for i in items], trace_id=_trace_id(request)),
    )


# ── Story 5.10: session-end trigger ────────────────────────────────────────────────


class ChatEndRequest(BaseModel):
    """Request body for POST /api/v1/support/chat/end (Story 5.10 AC #7)."""

    session_id: UUID


@router.post("/api/v1/support/chat/end", status_code=202)
async def end_chat_session(
    request: Request,
    body: ChatEndRequest,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Trigger the Conclusion Agent when a chat session ends (explicit close) (AC #7).

    The endpoint returns 202 Accepted immediately and fires the Conclusion Agent as
    a background task (asyncio.create_task). The agent loads session history from
    Valkey, summarizes it, stores learnings, and triggers the Notification Agent.

    This is the explicit-close trigger; the background TTL poll (main.py) handles
    sessions that expire due to 2-hour idle timeout.
    """
    db = _db(request)
    async with db.transaction() as conn:
        subscriber_id = await resolve_subscriber_id(conn, jwt_payload)

    conclusion_graph = get_conclusion_graph()

    if conclusion_graph is None:
        err = DomainError("Conclusion Agent graph is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err

    # Fire Conclusion Agent asynchronously (fire-and-forget)
    _task = asyncio.create_task(  # noqa: RUF006
        conclusion_graph.ainvoke(
            {
                "session_id": str(body.session_id),
                "subscriber_id": subscriber_id,
                "session_history": [],  # Will be loaded by load_session_history node
                "summary": None,  # Will be set by summarise_session node
                "trace_id": _trace_id(request),
            }
        )
    )

    logger.info(
        "Chat session ended: session=%s subscriber=%s trigger=explicit_close",
        body.session_id,
        subscriber_id,
    )

    return JSONResponse(
        status_code=202,
        content=success_envelope({"status": "accepted"}, trace_id=_trace_id(request)),
    )
