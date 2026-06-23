"""Recharge / plan-catalogue endpoints for authenticated subscribers (Story 3.4).

GET /api/v1/plans — browse all active plans (FR-12).

The catalogue is shared data (every subscriber sees the same plans), so it is
guarded by ``require_role("subscriber")`` only — there is no owner assertion.
Money is integer paise; ``data_limit_mb`` is converted to ``data_gb`` here at the
presentation boundary.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.auth import require_role
from core.errors import DomainError
from core.responses import success_envelope
from db.recharge.queries import get_active_plans
from models.plan import PlanCatalogueItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["recharge"])


def _db(request: Request):
    """Resolve the database adapter from app state."""
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        err = DomainError("Database adapter is not initialised.")
        err.code = "NOT_READY"
        err.http_status = 503
        raise err
    return db


def _trace_id(request: Request) -> str:
    """Return the OTEL trace id from request state, or 'unknown' if absent."""
    return getattr(request.state, "trace_id", "unknown")


@router.get("/plans", status_code=200)
async def list_plans(
    request: Request,
    jwt_payload: dict = require_role("subscriber"),
) -> JSONResponse:
    """Return all active plans for the catalogue (AC #3).

    Shared catalogue data — no owner assertion (every subscriber sees the same
    plans). ``data_gb = round(data_limit_mb / 1024, 2)``; ``None`` means
    unlimited. ``plan_type`` is ``None`` (V1 has no such column).
    """
    db = _db(request)

    async with db.transaction() as conn:
        rows = await get_active_plans(conn)

    def _data_gb(data_limit_mb: int | None) -> float | None:
        return round(data_limit_mb / 1024, 2) if data_limit_mb is not None else None

    items = [
        PlanCatalogueItem(
            id=row["id"],
            name=row["plan_name"],
            data_gb=_data_gb(row["data_limit_mb"]),
            voice_minutes=row["voice_minutes"],
            sms_count=row["sms_count"],
            validity_days=row["validity_days"],
            price_paise=row["price_paise"],
            plan_type=None,
        )
        for row in rows
    ]

    return JSONResponse(
        status_code=200,
        content=success_envelope(
            [item.model_dump(mode="json") for item in items],
            trace_id=_trace_id(request),
        ),
    )
