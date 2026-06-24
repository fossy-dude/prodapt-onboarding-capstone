"""Support Agent LangGraph tools (Story 5.4; architecture §1.6.1, FR-22/23/26).

The Support Agent's grounding surface — four ``@tool`` callables the supervisor
node binds onto the LLM so it can fetch *real* subscriber data instead of
hallucinating it:

* :func:`get_balance` — reads the Valkey-authoritative wallet balance
  (``balance:{msisdn}``, ARCH-6).
* :func:`get_plan` — active plan name / expiry / quotas
  (``plans_subscriptions JOIN plans_plans``).
* :func:`get_usage` — per-type CDR usage for the last N days
  (``billing_cdr_events``).
* :func:`rag_search` — delegates to the Story 5.3 hybrid retriever
  (``agents.rag.retriever``).

Dependency injection (architecture §1.6.1): LangGraph ``@tool`` callables have no
closure to thread DI through, so the cache + DB adapters are held as
process-wide singletons set once at FastAPI startup via
:func:`set_support_adapters` — the same pattern Story 5.3's ``set_retriever``
established. Callers MUST call :func:`set_support_adapters` before any tool runs
(the graph is unreachable before wiring, so a missing adapter raises loudly).

PII hygiene (ARCH-32 / §1.11.6): ``get_balance`` never returns the raw MSISDN —
only paise + a formatted INR string. The MSISDN is the caller's identity claim
(passed in already-masked from the agent state where required).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from langchain_core.tools import tool

from agents.rag.retriever import rag_search
from db.billing.queries import get_active_plan, get_usage_for_period

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORT_TOOLS",
    "get_balance",
    "get_plan",
    "get_usage",
    "rag_search_tool",
    "set_support_adapters",
]

# ── Process-wide singletons (set at FastAPI startup) ──────────────────────────
# Module-level on purpose: ``@tool`` callables resolve these at call time. Mirrors
# the ``set_retriever()`` singleton from Story 5.3 (architecture §1.6.1).
_cache: CacheProtocol | None = None
_db: DatabaseProtocol | None = None


def set_support_adapters(
    cache: CacheProtocol | None,
    db: DatabaseProtocol | None,
) -> None:
    """Set (or clear with ``None``) the cache + DB singletons the tools resolve.

    Called from the FastAPI lifespan / ``setup_copilotkit`` at boot so the tools
    can read live Valkey + Postgres. Tests call this to inject fakes.
    """
    global _cache, _db
    _cache = cache
    _db = db


def get_support_cache() -> CacheProtocol | None:
    """Return the cache singleton (or ``None`` if not wired) — used by the graph node."""
    return _cache


def _require_cache() -> CacheProtocol:
    if _cache is None:
        raise RuntimeError("Support tools not initialised — call set_support_adapters() at FastAPI startup")
    return _cache


def _require_db() -> DatabaseProtocol:
    if _db is None:
        raise RuntimeError("Support tools not initialised — call set_support_adapters() at FastAPI startup")
    return _db


@tool
async def get_balance(msisdn: str) -> dict:
    """Return the subscriber's current wallet balance.

    Reads the Valkey-authoritative counter ``balance:{msisdn}`` (ARCH-6). Returns
    ``{"balance_paise": int, "balance_inr": str}`` where ``balance_inr`` is a
    formatted ``₹RR.PP`` string. A cold cache (no key) returns ``None`` values so
    the agent can explain the balance is unavailable rather than fabricate one.
    """
    cache = _require_cache()
    balance_paise = await cache.get_balance(msisdn)
    if balance_paise is None:
        logger.debug("get_balance: cache-miss msisdn=%s", msisdn[-4:])
        return {"balance_paise": None, "balance_inr": None}
    return {
        "balance_paise": balance_paise,
        "balance_inr": f"₹{balance_paise / 100:.2f}",
    }


@tool
async def get_plan(subscriber_id: str) -> dict:
    """Return the subscriber's active plan: name, validity expiry and quotas.

    Joins the latest active ``plans_subscriptions`` to its ``plans_plans`` row
    (status='active'). Returns ``None`` when no active subscription exists so the
    agent can advise the subscriber to recharge.
    """
    db = _require_db()
    async with db.transaction() as conn:
        plan = await get_active_plan(conn, UUID(subscriber_id))
    if plan is None:
        return {"active_plan": None}
    end_date = plan["end_date"]
    return {
        "active_plan": {
            "plan_id": str(plan["plan_id"]),
            "plan_name": plan["plan_name"],
            "validity_expiry": end_date.isoformat() if end_date is not None else None,
            "validity_days": plan["validity_days"],
            "data_limit_mb": plan["data_limit_mb"],
            "voice_minutes": plan["voice_minutes"],
            "sms_count": plan["sms_count"],
        }
    }


@tool
async def get_usage(subscriber_id: str, days: int = 30) -> dict:
    """Aggregate per-type CDR usage (voice/data/SMS) for the last ``days`` days.

    Sums charged ``billing_cdr_events`` between ``now - days`` and ``now``. Voice is
    returned in minutes, data in MB and SMS as a count — the natural units the
    agent uses to answer "how much have I used" questions.
    """
    db = _require_db()
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    async with db.transaction() as conn:
        usage = await get_usage_for_period(conn, UUID(subscriber_id), start, end)
    return {
        "window_days": days,
        "voice_minutes": round(usage["voice_minutes_used"], 2),
        "data_mb": round(usage["data_mb_used"], 2),
        "sms_count": usage["sms_count_used"],
        "roaming_mb": round(usage["roaming_mb_used"], 2),
    }


@tool
async def rag_search_tool(query: str) -> list[dict]:
    """Hybrid (dense + BM25) RAG search over FAQ + plan knowledge chunks.

    Delegates to the Story 5.3 ``agents.rag.retriever.rag_search`` singleton.
    Returns a list of ``{collection, chunk_id, text, score}`` dicts — empty when
    no grounding clears the RRF no-match threshold (the agent then answers from
    its own knowledge or declines).
    """
    chunks = await rag_search(query)
    return [
        {
            "collection": c.collection,
            "chunk_id": c.chunk_id,
            "text": c.text,
            "score": c.score,
        }
        for c in chunks
    ]


# Convenience tuple the supervisor node binds onto the LLM (FR-22, FR-23, FR-26).
SUPPORT_TOOLS = [get_balance, get_plan, get_usage, rag_search_tool]
