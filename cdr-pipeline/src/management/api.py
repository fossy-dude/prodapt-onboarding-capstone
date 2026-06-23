"""CDR management API — DLQ inspect + worker control (Story 2.5, AC #1-#5).

FastAPI router mounted at ``/api/v1/admin`` on a dedicated management app.
All routes require role ``admin`` (``cognito:groups`` claim). Runs on the same
event loop as the consumer pool so ``WorkerController`` pause/resume is in-process.

Endpoints:
  GET  /api/v1/admin/dlq               — paginated DLQ list (PII-masked)
  GET  /api/v1/admin/dlq/{cdr_id}      — single DLQ event (PII-masked)
  POST /api/v1/admin/workers/pause     — pause consumer polling (≤2s)
  POST /api/v1/admin/workers/resume    — resume consumer polling
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query, Request

from core.auth import require_role
from core.errors import NotFoundError
from core.responses import success_envelope

if TYPE_CHECKING:
    from consumer.control import WorkerController

logger = logging.getLogger("management.api")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Regexes for PII masking in raw DLQ payloads (§1.11.6).
# MSISDN: match 8-10 digits followed by last 4 (handles 12-digit with country code like 91XXXXXXXXXX)
_MSISDN_RE = re.compile(r"\b(\d{8,10})(\d{4})\b")
# IMEI: match 15-digit IMEI (standard) - redact all
_IMEI_RE = re.compile(r"\b\d{15}\b")


def _mask_payload(raw: str) -> str:
    """Mask MSISDNs (keep last 4) and IMEIs (redact all) in a raw JSON string."""
    masked = _MSISDN_RE.sub(lambda m: f"{'*' * len(m.group(1))}{m.group(2)}", raw)
    masked = _IMEI_RE.sub("***************", masked)
    return masked


def _trace(request: Request) -> str:
    return getattr(request.state, "trace_id", "unknown")


def _parse_dlq_record(record_value: bytes) -> dict[str, Any] | None:
    """Decode an aiokafka ConsumerRecord value into DLQ metadata dict.

    Returns ``None`` if the record cannot be parsed (malformed envelope).
    The DLQ envelope wraps the payload written by Story 2.2's ``dlq/handler.py``:
    ``{cdr_id, error_reason, original_topic, failed_at, raw_payload_b64}``.
    """
    try:
        outer = json.loads(record_value.decode("utf-8"))
        payload = outer.get("payload", outer)
        return {
            "cdr_id": payload.get("cdr_id"),
            "error_reason": payload.get("error_reason"),
            "original_topic": payload.get("original_topic"),
            "failed_at": payload.get("failed_at"),
            "raw_payload_b64": payload.get("raw_payload_b64"),
        }
    except Exception:
        return None


def _raw_payload_preview(b64: str | None) -> str:
    """Decode base64 raw payload → mask PII → return first 500 chars."""
    if not b64:
        return ""
    try:
        raw_bytes = base64.b64decode(b64)
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        return _mask_payload(raw_str)[:500]
    except Exception:
        return ""


def _full_raw_payload(b64: str | None) -> str:
    """Decode base64 raw payload → mask PII → return full (masked) string."""
    if not b64:
        return ""
    try:
        raw_bytes = base64.b64decode(b64)
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        return _mask_payload(raw_str)
    except Exception:
        return ""


async def _fetch_dlq_records(request: Request) -> list[dict[str, Any]]:
    """Consume ``cdr.dlq`` via a transient non-committing consumer and return all records.

    Uses ``auto_offset_reset="earliest"`` + no commit so inspection does not
    advance consumer offsets (the DLQ is not consumed / depleted by inspection).
    """
    from aiokafka import AIOKafkaConsumer  # noqa: PLC0415

    from core.config import settings  # noqa: PLC0415

    dlq_consumer = AIOKafkaConsumer(
        "cdr.dlq",
        bootstrap_servers=settings.kafka_brokers,
        group_id=f"cdr-dlq-inspector-{datetime.now(UTC).timestamp()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    records: list[dict[str, Any]] = []
    try:
        await dlq_consumer.start()
        # Give the consumer a short window to fetch available records.
        # ``getmany`` returns immediately if no records are available within the timeout.
        batch = await dlq_consumer.getmany(timeout_ms=3000, max_records=10000)
        for topic_records in batch.values():
            for rec in topic_records:
                raw_value: bytes = rec.value or b""
                parsed = _parse_dlq_record(raw_value)
                if parsed is not None:
                    records.append(parsed)
    finally:
        await dlq_consumer.stop()
    return records


@router.get("/dlq")
async def list_dlq(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _payload: dict = require_role("admin"),
) -> dict[str, Any]:
    """Return a paginated list of DLQ events with PII-masked preview (AC #1)."""
    records = await _fetch_dlq_records(request)
    total = len(records)
    page = records[offset : offset + limit]

    items = [
        {
            "cdr_id": r["cdr_id"],
            "error_reason": r["error_reason"],
            "original_topic": r["original_topic"],
            "failed_at": r["failed_at"],
            "raw_payload_preview": _raw_payload_preview(r.get("raw_payload_b64")),
        }
        for r in page
    ]
    return success_envelope(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        trace_id=_trace(request),
    )


@router.get("/dlq/{cdr_id}")
async def get_dlq_event(
    cdr_id: str,
    request: Request,
    _payload: dict = require_role("admin"),
) -> dict[str, Any]:
    """Return the full (PII-masked) raw payload for a single DLQ event (AC #2)."""
    records = await _fetch_dlq_records(request)
    match = next((r for r in records if r.get("cdr_id") == cdr_id), None)
    if match is None:
        raise NotFoundError(f"DLQ record not found: {cdr_id}")

    return success_envelope(
        {
            "cdr_id": match["cdr_id"],
            "error_reason": match["error_reason"],
            "original_topic": match["original_topic"],
            "failed_at": match["failed_at"],
            "raw_payload": _full_raw_payload(match.get("raw_payload_b64")),
        },
        trace_id=_trace(request),
    )


@router.post("/workers/pause")
async def pause_workers(
    request: Request,
    _payload: dict = require_role("admin"),
) -> dict[str, Any]:
    """Pause CDR consumer polling within 2s (AC #3)."""
    controller: WorkerController = request.app.state.worker_controller
    controller.pause()
    logger.info("CDR workers paused by admin (sub=%s)", _payload.get("sub", "unknown"))
    return success_envelope({"status": "paused"}, trace_id=_trace(request))


@router.post("/workers/resume")
async def resume_workers(
    request: Request,
    _payload: dict = require_role("admin"),
) -> dict[str, Any]:
    """Resume CDR consumer polling (AC #4)."""
    controller: WorkerController = request.app.state.worker_controller
    controller.resume()
    logger.info("CDR workers resumed by admin (sub=%s)", _payload.get("sub", "unknown"))
    return success_envelope({"status": "running"}, trace_id=_trace(request))


__all__ = ["router"]
