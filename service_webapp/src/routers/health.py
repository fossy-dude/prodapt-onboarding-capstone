"""Health & readiness endpoints (Story 1.4; architecture §1.11.3, §1.15.1).

``GET /health`` — liveness: instant 200 ``{"status": "ok"}``, no dependency
checks, no auth.

``GET /ready`` — readiness: pings the Postgres pool + Valkey; 200 only if both are
healthy, otherwise 503 with the standard error envelope. Both are cheap (< 200ms)
and require no auth (architecture §1.11.3 envelope, §1.15.1 verify step).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — always 200 while the process is up; touches no dependencies."""
    return {"status": "ok"}


def _error_envelope(request: Request, code: str, message: str, detail: dict[str, bool]) -> dict[str, Any]:
    """Build the standard API error envelope (architecture §1.11.3)."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    return {
        "error": {"code": code, "message": message, "detail": detail},
        "meta": {"trace_id": trace_id, "timestamp": datetime.now(UTC).isoformat()},
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — 200 only when Postgres and Valkey are both reachable."""
    db_adapter = getattr(request.app.state, "db_adapter", None)
    cache_adapter = getattr(request.app.state, "cache_adapter", None)

    if db_adapter is None or cache_adapter is None:
        return JSONResponse(
            status_code=503,
            content=_error_envelope(
                request,
                code="NOT_READY",
                message="Adapters not initialized — lifespan may not have run",
                detail={"postgres": False, "valkey": False},
            ),
        )

    # Probe both dependencies concurrently so worst-case latency is max(ping_db, ping_cache),
    # not their sum (NFR-19: each is bounded to 2 s; serial would allow 4 s total).
    postgres_ok, valkey_ok = await asyncio.gather(db_adapter.ping(), cache_adapter.ping())
    detail = {"postgres": postgres_ok, "valkey": valkey_ok}

    if postgres_ok and valkey_ok:
        return JSONResponse(status_code=200, content={"status": "ready", "detail": detail})

    return JSONResponse(
        status_code=503,
        content=_error_envelope(
            request,
            code="NOT_READY",
            message="One or more dependencies are unhealthy",
            detail=detail,
        ),
    )
