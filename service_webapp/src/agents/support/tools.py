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

import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import UUID

from langchain_core.tools import tool

from agents.rag.retriever import rag_search
from agents.support.identity import current_msisdn, current_session_id, current_subscriber_id
from core.observability.langfuse import get_langfuse_client
from core.security import mask_msisdn
from db.billing.queries import get_active_plan, get_usage_for_period
from db.plans.queries import get_available_plans, get_payment_method_for_subscriber

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agents.rating.graph import ChargeBreakdown
    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol

__all__ = [
    "SUPPORT_TOOLS",
    "charge_explain",
    "get_balance",
    "get_plan",
    "get_support_db",
    "get_usage",
    "list_plans",
    "rag_search_tool",
    "recharge_flow",
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


def get_support_db() -> DatabaseProtocol | None:
    """Return the DB singleton (or ``None`` if not wired).

    Used by the guardrail node for best-effort audit logging without forcing the
    tools to be initialised.
    """
    return _db


def _require_cache() -> CacheProtocol:
    if _cache is None:
        raise RuntimeError("Support tools not initialised — call set_support_adapters() at FastAPI startup")
    return _cache


def _require_db() -> DatabaseProtocol:
    if _db is None:
        raise RuntimeError("Support tools not initialised — call set_support_adapters() at FastAPI startup")
    return _db


@tool
async def get_balance() -> dict:
    """Return the *authenticated* subscriber's current wallet balance.

    Reads the Valkey-authoritative counter ``balance:{msisdn}`` (ARCH-6), where the
    MSISDN is resolved server-side from the request's JWT (never supplied by the
    LLM — see :mod:`agents.support.identity`). Returns
    ``{"balance_paise": int, "balance_inr": str}`` where ``balance_inr`` is a
    formatted rupee string. A cold cache (no key) returns ``None`` values so the
    agent can explain the balance is unavailable rather than fabricate one.
    """
    cache = _require_cache()
    msisdn = current_msisdn()
    balance_paise = await cache.get_balance(msisdn)
    if balance_paise is None:
        logger.debug("get_balance: cache-miss msisdn=%s", mask_msisdn(msisdn))
        return {"balance_paise": None, "balance_inr": None}
    # Guard against a non-int counter value (defensive: the contract is int, but a
    # corrupt/manual Valkey entry must not crash formatting). Negative balances
    # render as ``-₹RR.PP`` (debt) rather than the malformed ``₹-RR.PP``.
    paise = int(balance_paise)
    sign = "-" if paise < 0 else ""
    return {
        "balance_paise": paise,
        "balance_inr": f"{sign}₹{abs(paise) / 100:.2f}",
    }


@tool
async def get_plan() -> dict:
    """Return the *authenticated* subscriber's active plan: name, expiry, quotas.

    Joins the latest active ``plans_subscriptions`` to its ``plans_plans`` row
    (status='active'), scoped to the JWT ``sub`` (never supplied by the LLM — see
    :mod:`agents.support.identity`). Returns ``None`` when no active subscription
    exists so the agent can advise the subscriber to recharge.
    """
    db = _require_db()
    async with db.transaction() as conn:
        plan = await get_active_plan(conn, UUID(current_subscriber_id()))
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
async def get_usage(days: int = 30) -> dict:
    """Aggregate per-type CDR usage (voice/data/SMS) for the last ``days`` days.

    Sums charged ``billing_cdr_events`` between ``now - days`` and ``now`` for the
    *authenticated* subscriber (JWT ``sub`` — never supplied by the LLM). Voice is
    returned in minutes, data in MB and SMS as a count — the natural units the
    agent uses to answer "how much have I used" questions.
    """
    db = _require_db()
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    async with db.transaction() as conn:
        usage = await get_usage_for_period(conn, UUID(current_subscriber_id()), start, end)
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


_MAX_PLANS = 20


def _plan_to_card(p: dict) -> dict:
    """Serialize a raw plan row into the chat-UI plan-card dict.

    Extracted from the (former) triplicated list_plans branches so the shape is
    defined once. Guards ``price_paise`` with ``int()`` so a corrupt non-int
    value cannot crash the ``price_inr`` formatting.
    """
    price_paise = int(p["price_paise"])
    return {
        "plan_id": str(p["id"]),
        "name": p["plan_name"],
        "price_paise": price_paise,
        "price_inr": f"₹{price_paise / 100:.2f}",
        "data_limit_mb": p["data_limit_mb"],
        "voice_minutes": p["voice_minutes"],
        "sms_count": p["sms_count"],
    }


async def _run_list_plans(top_n: int) -> dict:
    """Fetch the ``top_n`` cheapest active plans and serialize them.

    Clamps ``top_n`` to ``[1, _MAX_PLANS]`` before querying.
    """
    clamped = max(1, min(int(top_n), _MAX_PLANS))
    db = _require_db()
    async with db.transaction() as conn:
        raw_plans = await get_available_plans(conn, limit=clamped)
    return {"plans": [_plan_to_card(p) for p in raw_plans]}


async def _run_recharge_flow(plan_id: str) -> dict:
    """Resolve the recharge deeplink for the authenticated subscriber.

    Validates ``plan_id`` as a UUID, checks for a saved payment method (resolved
    server-side via :func:`current_subscriber_id`), and returns either a
    ``no_payment_method`` message or a ``deeplink`` URL whose query key is
    ``plan_id``.
    """
    try:
        plan_uuid = UUID(plan_id)
    except (TypeError, ValueError):
        return {
            "status": "invalid_plan",
            "url": None,
            "message": "That plan id isn't valid. Please pick a plan from the list.",
        }
    db = _require_db()
    async with db.transaction() as conn:
        payment_method = await get_payment_method_for_subscriber(conn, current_subscriber_id())
    if payment_method is None:
        return {
            "status": "no_payment_method",
            "url": None,
            "message": "You don't have a saved payment method. Please add one at Settings > Payment Methods.",
        }
    recharge_url = f"/subscriber/recharge?plan_id={quote(str(plan_uuid))}"
    return {
        "status": "deeplink",
        "url": recharge_url,
        "message": f"To complete your recharge, click here: {recharge_url}. Your saved payment method will be pre-selected.",
    }


async def _traced_tool(name: str, args: dict, core) -> dict:
    """Run ``core()`` (a no-arg async returning a dict), traced as a LangFuse tool_call span.

    Single implementation (no triplication): no-op when LangFuse is disabled, falls back
    to untraced on span-open failure, and tags level=ERROR on a core() failure. Uses a
    proper ``with`` context manager — never a hand-rolled __exit__ (cf. graph.py guidance).
    """
    client = get_langfuse_client()
    if client is None:
        return await core()
    try:
        cm = client.start_as_current_observation(name="tool_call", as_type="span", input={"tool": name, "args": args})
    except Exception as exc:
        logger.warning("LangFuse %s span open failed: %s", name, exc)
        return await core()
    with cm as observation:
        try:
            result = await core()
        except Exception as exc:
            try:
                observation.update(level="ERROR", status_message=str(exc))
            except Exception:
                pass
            raise
        try:
            observation.update(output=result)
        except Exception as exc:
            logger.warning("LangFuse %s span update failed: %s", name, exc)
        return result


@tool
async def list_plans(top_n: int = 3) -> dict:
    """Return the top ``top_n`` cheapest active plans for the subscriber.

    Queries ``plans_plans`` for active plans ordered by price ascending. The
    subscriber is resolved server-side (never supplied by the LLM — see
    :mod:`agents.support.identity`). Returns a list of plan cards the chat UI
    renders as ``<PlanRecommendationCard>`` components. Each plan includes a
    formatted ``price_inr`` string for display.

    Parameters
    ----------
    top_n : int
        Maximum number of plans to return (default: 3; clamped to ``[1, 20]``).

    Returns
    -------
    dict
        ``{"plans": [...]}`` where each plan has ``plan_id``, ``name``, ``price_paise``,
        ``price_inr``, ``data_limit_mb``, ``voice_minutes``, ``sms_count``.
    """
    return await _traced_tool("list_plans", {"top_n": top_n}, lambda: _run_list_plans(top_n))


@tool
async def recharge_flow(plan_id: str) -> dict:
    """Return a deeplink to the recharge portal for the selected plan.

    Checks whether the subscriber has a saved payment method (resolved
    server-side via :func:`current_subscriber_id` — never supplied by the LLM).
    If not, returns a message prompting them to add one. If a payment method
    exists, returns a deeplink URL to ``/subscriber/recharge?plan_id={plan_id}``
    — the portal handles the actual payment (architecture decision: deeplink,
    not direct API call).

    Parameters
    ----------
    plan_id : str
        Plan UUID string for the recharge target. Validated as a UUID; a
        non-UUID value returns an ``invalid_plan`` status.

    Returns
    -------
    dict
        ``{"status": "deeplink" | "no_payment_method" | "invalid_plan",
        "url": str | None, "message": str}``
    """
    return await _traced_tool("recharge_flow", {"plan_id": plan_id}, lambda: _run_recharge_flow(plan_id))


async def _run_charge_explain(subscriber_id: str, cdr_reference: str) -> dict:
    """Core charge_explain logic: invoke Rating Agent A2A and return breakdown.

    This is an A2A (agent-to-agent) call — the Support Agent invokes the
    Rating Agent's compiled LangGraph graph directly via ``await rating_graph.ainvoke()``
    (not HTTP or Kafka). Both agents run in the same ``service_webapp`` FastAPI
    process (architecture §1.6.1).

    Parameters
    ----------
    subscriber_id : str
        Subscriber UUID string.
    cdr_reference : str
        CDR event ID to fetch breakdown for.

    Returns
    -------
    dict
        ``{"found": bool, "breakdown": dict | None, "message": str}``
        where ``breakdown`` is the ChargeBreakdown data when found.
    """
    # Import inside function to avoid circular import
    from agents.rating.graph import rating_graph

    try:
        # Invoke Rating Agent via A2A (same-process LangGraph call)
        result = await rating_graph.ainvoke(
            {
                "subscriber_id": subscriber_id,
                "cdr_reference": cdr_reference,
                "trace_id": current_session_id() or "unknown",
                "result": None,
            }
        )

        breakdown = result.get("result")
        if breakdown is None:
            return {
                "found": False,
                "breakdown": None,
                "message": "I couldn't find a charge with that reference. Could you provide the date instead?",
            }

        # Convert dataclass to dict for tool return
        return {
            "found": True,
            "breakdown": dataclasses.asdict(breakdown),
            "message": f"Found charge details for {breakdown.event_type} event",
        }

    except Exception:
        logger.exception("charge_explain failed for subscriber=%s cdr=%s", subscriber_id, cdr_reference)
        return {
            "found": False,
            "breakdown": None,
            "message": "I encountered an error looking up that charge. Please try again later.",
        }


@tool
async def charge_explain(subscriber_id: str, cdr_reference: str) -> dict:
    """Fetch detailed charge breakdown for a specific CDR event (Story 5.7).

    Invokes the Rating Agent (A2A) to query billing_audit_log and plan
    configuration, returning a structured charge breakdown including
    duration/data, rate per unit, charge amount, and balance impact.

    The subscriber_id is resolved server-side from JWT (never supplied by
    the LLM — see :mod:`agents.support.identity`).

    Parameters
    ----------
    subscriber_id : str
        Subscriber UUID string (validated server-side).
    cdr_reference : str
        CDR event UUID to fetch breakdown for.

    Returns
    -------
    dict
        ``{"found": bool, "breakdown": dict | None, "message": str}``
        where ``breakdown`` contains:
        ``{cdr_id, event_type, duration_or_data, rate_per_unit,
        charge_paise, balance_before, balance_after}``
    """
    # Use current subscriber ID from context for security (ignore LLM-provided value)
    actual_subscriber_id = current_subscriber_id()

    return await _traced_tool(
        "charge_explain",
        {"subscriber_id": actual_subscriber_id, "cdr_reference": cdr_reference},
        lambda: _run_charge_explain(actual_subscriber_id, cdr_reference),
    )


# Convenience tuple the supervisor node binds onto the LLM (FR-22, FR-23, FR-26, Story 5.6, Story 5.7).
SUPPORT_TOOLS = [get_balance, get_plan, get_usage, rag_search_tool, list_plans, recharge_flow, charge_explain]
