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

from agents.rag.retriever import (
    rag_search,
    search_plans as _search_plans,
)
from agents.support.identity import current_msisdn, current_session_id, current_subscriber_id
from core.observability.langfuse import get_langfuse_client
from core.security import mask_msisdn
from db.billing.queries import (
    get_active_plan,
    get_current_plan_details,
    get_last_recharge_amount,
    get_population_usage_stats,
    get_subscriber_usage_profile,
    get_usage_for_period,
)
from db.plans.queries import get_available_plans, get_payment_method_for_subscriber
from db.support.commands import create_ticket

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agents.rating.graph import ChargeBreakdown
    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol

__all__ = [
    "SUPPORT_TOOLS",
    "balance_lookup",
    "charge_explain",
    "get_balance",
    "get_plan",
    "get_support_db",
    "get_usage",
    "list_plans",
    "rag_search_tool",
    "recharge_flow",
    "recommend_plan",
    "set_support_adapters",
    "ticket_create",
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
    from agents.rating.graph import rating_graph  # noqa: PLC0415

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


# ── Plan recommendation helpers (Story 5.9) ────────────────────────────────────


def _percentile_rank(value: float, p25: float, p50: float, p75: float, p90: float) -> float:
    if p25 == 0 and p50 == 0:
        return 0.0
    if value <= p25:
        return 25.0 * (value / p25) if p25 > 0 else 0.0
    if value <= p50:
        return 25.0 + 25.0 * ((value - p25) / (p50 - p25)) if p50 > p25 else 25.0
    if value <= p75:
        return 50.0 + 25.0 * ((value - p50) / (p75 - p50)) if p75 > p50 else 50.0
    if value <= p90:
        return 75.0 + 15.0 * ((value - p75) / (p90 - p75)) if p90 > p75 else 75.0
    return 91.0


def _build_plan_comparison(current: dict | None, rec_metadata: dict) -> str | None:
    if not current:
        return None

    parts = []

    cur_data = current.get("data_limit_mb") or 0
    rec_data = rec_metadata.get("data_limit_mb") or 0
    if cur_data > 0 and rec_data > 0:
        diff_pct = (rec_data - cur_data) / cur_data * 100
        if abs(diff_pct) >= 10:
            label = "more" if diff_pct > 0 else "less"
            parts.append(f"{abs(diff_pct):.0f}% {label} data")
    elif rec_data > 0 and cur_data == 0:
        parts.append(f"{rec_data / 1024:.1f}GB data")

    cur_voice = current.get("voice_minutes")
    rec_voice_raw = rec_metadata.get("voice_minutes")
    rec_voice = None if rec_voice_raw == 0 else rec_voice_raw
    if cur_voice is not None and rec_voice is not None:
        diff = rec_voice - cur_voice
        if abs(diff) >= 50:
            label = "more" if diff > 0 else "fewer"
            parts.append(f"{abs(diff)} {label} min")
    elif rec_voice is None and cur_voice is not None:
        parts.append("unlimited calls")

    price_diff_paise = rec_metadata.get("price", 0) - current.get("price_paise", 0)
    if price_diff_paise != 0:
        label = "more" if price_diff_paise > 0 else "less"
        parts.append(f"₹{abs(price_diff_paise) // 100} {label}")

    return " · ".join(parts) if parts else None


_PREF_MAP: dict[str, str] = {
    "data": "DATA_HEAVY",
    "voice": "VOICE_HEAVY",
    "value": "VALUE",
    "balanced": "BALANCED",
}

_DOMINANT_THRESHOLD = 70.0


async def _run_recommend_plan(preference: str | None) -> dict:
    subscriber_id = current_subscriber_id()
    db = _require_db()

    async with db.transaction() as conn:
        profile = await get_subscriber_usage_profile(conn, UUID(subscriber_id))

        if preference is not None:
            category = _PREF_MAP.get(preference.lower(), "BALANCED")
        else:
            pop_stats = await get_population_usage_stats(conn)
            if not pop_stats:
                category = "BALANCED"
            else:
                data_pct = _percentile_rank(
                    profile["total_data_mb"],
                    pop_stats.get("data_p25", 0),
                    pop_stats.get("data_p50", 0),
                    pop_stats.get("data_p75", 0),
                    pop_stats.get("data_p90", 0),
                )
                voice_pct = _percentile_rank(
                    profile["total_voice_seconds"],
                    pop_stats.get("voice_p25", 0),
                    pop_stats.get("voice_p50", 0),
                    pop_stats.get("voice_p75", 0),
                    pop_stats.get("voice_p90", 0),
                )
                intl_pct = _percentile_rank(
                    profile["total_intl_seconds"],
                    pop_stats.get("intl_p25", 0),
                    pop_stats.get("intl_p50", 0),
                    pop_stats.get("intl_p75", 0),
                    pop_stats.get("intl_p90", 0),
                )
                scores: dict[str, float] = {
                    "DATA_HEAVY": data_pct,
                    "VOICE_HEAVY": max(voice_pct, intl_pct),
                }
                dominant = {cat: pct for cat, pct in scores.items() if pct >= _DOMINANT_THRESHOLD}
                if not dominant:
                    return {
                        "needs_clarification": True,
                        "question": "What matters most to you — more data, more calling minutes, or a lower cost?",
                    }
                category = max(dominant, key=dominant.get)

        last = await get_last_recharge_amount(conn, UUID(subscriber_id))
        current_plan = await get_current_plan_details(conn, UUID(subscriber_id))

    data_gb = profile["total_data_mb"] / 1024
    voice_min = profile["total_voice_seconds"] // 60
    intl_min = profile["total_intl_seconds"] // 60
    query_text = f"data {profile['total_data_mb']:.0f}MB voice {voice_min}min intl {intl_min}min"

    filter_expr = f"usage_category == '{category}'" if category != "VALUE" else None
    chunks = await _search_plans(query_text, top_k=10, filter_expr=filter_expr)

    if last is not None:
        low, high = last * 0.8, last * 1.2
        chunks = [c for c in chunks if low <= c.metadata.get("price", 0) <= high]

    if category == "VALUE":
        chunks = sorted(chunks, key=lambda c: c.metadata.get("price", 0))

    plans = []
    for c in chunks[:2]:
        price_paise = c.metadata.get("price", 0)
        plans.append(
            {
                "plan_id": c.metadata["plan_id"],
                "name": c.text.split()[0] if c.text else "",
                "price_paise": price_paise,
                "price_inr": f"₹{price_paise // 100}",
                "rationale": (
                    f"Based on your {data_gb:.1f}GB data usage this month, "
                    f"{c.text} gives you more data at ₹{price_paise // 100}."
                ),
                "recharge_url": f"/subscriber/recharge?plan={c.metadata['plan_id']}",
                "comparison": _build_plan_comparison(current_plan, c.metadata),
            }
        )

    return {"plans": plans}


@tool
async def recommend_plan(subscriber_id: str, preference: str | None = None) -> dict:
    """Recommend the best plans for the subscriber based on their usage profile.

    preference: 'data' | 'voice' | 'value' | None. When None, classifies
    automatically using 30-day CDR usage percentiles. Returns
    ``{"needs_clarification": True, "question": "..."}`` when the usage profile
    is ambiguous and the subscriber must specify a preference.
    """
    actual_subscriber_id = current_subscriber_id()
    return await _traced_tool(
        "recommend_plan",
        {"subscriber_id": actual_subscriber_id, "preference": preference},
        lambda: _run_recommend_plan(preference),
    )


# ── Billing dispute ticket creation (Story 5.8) ───────────────────────────────


async def _run_ticket_create(subscriber_id: str, cdr_reference: str, charge_paise: int) -> dict:
    """Core ticket_create logic: persist a billing-dispute ticket via the support DB command."""
    db = _require_db()
    async with db.transaction() as conn:
        ticket = await create_ticket(
            conn,
            subscriber_id=subscriber_id,
            cdr_reference=cdr_reference,
            charge_paise=charge_paise,
            dispute_reason="subscriber_initiated",
        )
    ticket_id = str(ticket["id"])
    return {
        "ticket_id": ticket_id,
        "status": ticket["status"],
        "message": f"Ticket #{ticket_id} has been created. Our team will review it within 48 hours.",
    }


@tool
async def ticket_create(subscriber_id: str, cdr_reference: str, charge_paise: int) -> dict:
    """Create a billing-dispute support ticket for the authenticated subscriber (Story 5.8).

    Used at the end of the dispute multi-turn flow: the agent first presents the
    charge breakdown via ``charge_explain`` (Rating Agent A2A), the subscriber
    confirms the charge is wrong, then this tool creates the ticket. The
    subscriber is resolved server-side (``current_subscriber_id`` — never supplied
    by the LLM); ``dispute_reason`` is hardcoded to ``subscriber_initiated`` (no
    free text / PII in the ticket).

    Parameters
    ----------
    subscriber_id : str
        Subscriber UUID string (ignored — resolved from the JWT ``sub``).
    cdr_reference : str
        The disputed CDR event UUID.
    charge_paise : int
        The disputed charge amount in paise (from the presented breakdown).

    Returns
    -------
    dict
        ``{"ticket_id": str, "status": str, "message": str}`` where ``message``
        echoes the ticket id and the 48-hour review SLA the agent shows the user.
    """
    actual_subscriber_id = current_subscriber_id()
    return await _traced_tool(
        "ticket_create",
        {"subscriber_id": actual_subscriber_id, "cdr_reference": cdr_reference, "charge_paise": charge_paise},
        lambda: _run_ticket_create(actual_subscriber_id, cdr_reference, charge_paise),
    )


# ── Balance Management Agent (A2A) lookup (Story 5.8) ──────────────────────────


async def _run_balance_lookup(msisdn: str) -> dict:
    """Core balance_lookup logic: invoke the Balance Management Agent graph (A2A).

    The A2A call is traced as a LangFuse child span (``a2a_balance_agent``) nested
    under the Support Agent trace (FR-72); the outer ``balance_lookup`` tool wraps
    this in its own ``tool_call`` span. A cold Valkey key (no ``balance:{msisdn}``)
    yields ``0`` so the agent can say "your balance is ₹0.00" rather than
    "unavailable" — distinct from the Support Agent's direct ``get_balance`` tool
    which returns ``None`` on a cache miss (architecture §1.6.1).
    """
    from agents.balance.graph import balance_graph  # noqa: PLC0415

    async def _invoke_a2a() -> dict:
        return await balance_graph.ainvoke(
            {"msisdn": msisdn, "balance_paise": None, "trace_id": current_session_id() or "unknown"}
        )

    try:
        result = await _traced_tool("a2a_balance_agent", {"msisdn": mask_msisdn(msisdn)}, _invoke_a2a)
    except Exception:
        logger.exception("balance_lookup A2A failed for msisdn=%s", mask_msisdn(msisdn))
        return {
            "balance_paise": None,
            "balance_inr": None,
            "message": "I encountered an error checking your balance. Please try again later.",
        }

    balance_paise = result.get("balance_paise")
    if balance_paise is None:
        return {
            "balance_paise": None,
            "balance_inr": None,
            "message": "I couldn't retrieve your wallet balance right now. Please try again later.",
        }
    paise = int(balance_paise)
    sign = "-" if paise < 0 else ""
    return {"balance_paise": paise, "balance_inr": f"{sign}₹{abs(paise) / 100:.2f}"}


@tool
async def balance_lookup(msisdn: str) -> dict:
    """Look up the subscriber's wallet balance via the Balance Management Agent (A2A) (Story 5.8).

    For the "what's my wallet balance?" intent the Support Agent invokes the
    Balance Management Agent graph (A2A) which reads the Valkey authoritative
    counter ``balance:{msisdn}``. The A2A call is traced as a LangFuse child span
    (``a2a_balance_agent``) under the Support Agent trace (FR-72). The MSISDN is
    resolved server-side (``current_msisdn`` — never supplied by the LLM).

    Parameters
    ----------
    msisdn : str
        Subscriber MSISDN (ignored — resolved from the JWT identity claim).

    Returns
    -------
    dict
        ``{"balance_paise": int | None, "balance_inr": str | None,
        "message": str | None}``. ``balance_inr`` is a formatted rupee string; a
        cold cache yields ``balance_paise = 0`` (₹0.00).
    """
    actual_msisdn = current_msisdn()
    return await _traced_tool(
        "balance_lookup",
        {"msisdn": mask_msisdn(actual_msisdn)},
        lambda: _run_balance_lookup(actual_msisdn),
    )


# Convenience tuple the supervisor node binds onto the LLM (FR-22, FR-23, FR-26, Story 5.6/5.7/5.8/5.9).
SUPPORT_TOOLS = [
    get_balance,
    get_plan,
    get_usage,
    rag_search_tool,
    list_plans,
    recharge_flow,
    charge_explain,
    recommend_plan,
    ticket_create,
    balance_lookup,
]
