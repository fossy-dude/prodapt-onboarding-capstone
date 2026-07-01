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


async def _run_charge_explain(subscriber_id: str, user_query: str, cdr_reference: str | None) -> dict:
    """Core charge_explain logic: invoke Rating Agent A2A and return breakdown.

    This is an A2A (agent-to-agent) call — the Support Agent invokes the
    Rating Agent's compiled LangGraph graph directly via ``await rating_graph.ainvoke()``
    (not HTTP or Kafka). Both agents run in the same ``service_webapp`` FastAPI
    process (architecture §1.6.1).

    Parameters
    ----------
    subscriber_id : str
        Subscriber UUID string.
    user_query : str
        Subscriber's charge explanation question.
    cdr_reference : str | None
        Optional CDR event ID when already known.

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
                "user_query": user_query or "Explain this charge.",
                "cdr_reference": cdr_reference,
                "trace_id": current_session_id() or "unknown",
                "result": None,
            }
        )

        breakdown = result.get("result")
        summary = result.get("summary")
        if breakdown is None:
            return {
                "found": False,
                "breakdown": None,
                "message": summary
                or "I couldn't find a charge from those details. Please provide the CDR reference or date/time.",
            }

        # Convert dataclass to dict for tool return
        return {
            "found": True,
            "breakdown": dataclasses.asdict(breakdown),
            "message": summary or f"Found charge details for {breakdown.event_type} event",
        }

    except Exception:
        logger.exception("charge_explain failed for subscriber=%s cdr=%s", subscriber_id, cdr_reference)
        return {
            "found": False,
            "breakdown": None,
            "message": "I encountered an error looking up that charge. Please try again later.",
        }


@tool
async def charge_explain(user_query: str = "", cdr_reference: str | None = None) -> dict:
    """Explain a charge by invoking the LLM-powered Rating Agent (Story 5.7).

    Pass the subscriber's full charge question in ``user_query``. Include
    ``cdr_reference`` when the user provided a CDR/reference UUID. The Rating
    Agent chooses the appropriate rating tools for exact CDR lookup, time-window
    search, and balance checks, then returns a concise explanation.

    The subscriber is resolved server-side from the JWT.

    Parameters
    ----------
    user_query : str
        Original subscriber question about the charge.
    cdr_reference : str | None
        Optional CDR event UUID when supplied by the subscriber.

    Returns
    -------
    dict
        ``{"found": bool, "breakdown": dict | None, "message": str}``
        where ``breakdown`` contains:
        ``{cdr_id, event_type, duration_or_data, rate_per_unit,
        charge_paise, balance_before, balance_after}``
    """
    actual_subscriber_id = current_subscriber_id()

    return await _traced_tool(
        "charge_explain",
        {"subscriber_id": actual_subscriber_id, "user_query": user_query, "cdr_reference": cdr_reference},
        lambda: _run_charge_explain(actual_subscriber_id, user_query, cdr_reference),
    )


# ── Plan recommendation helpers (Story 5.9) ────────────────────────────────────

# plans_plans.{data_limit_mb,voice_minutes,sms_count} are NULL for "unlimited".
# Milvus filters need a real number, so plan_vectors stores unlimited as this
# sentinel (see scripts/seed_milvus.py) — bigger than any real plan value, so
# "more than current" correctly favors unlimited plans and "less than current"
# correctly excludes them.
_UNLIMITED_SENTINEL = 2_000_000_000

_VALID_DIRECTIONS = {"more", "less"}

# Maps a preference axis to its plan_vectors metadata field.
_AXIS_FIELDS: dict[str, str] = {
    "data": "data_limit_mb",
    "voice": "voice_minutes",
    "sms": "sms_count",
}


def _normalize_direction(value: str | None) -> str | None:
    """Coerce a preference into 'more' | 'less' | None, dropping anything else."""
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in _VALID_DIRECTIONS else None


def _normalize_limit(value: int | None) -> int:
    """Map a nullable plan limit to a comparable int, using the unlimited sentinel."""
    return _UNLIMITED_SENTINEL if value is None else int(value)


def _current_baseline(profile: dict, current_plan: dict | None) -> dict[str, int]:
    """Return the subscriber's current data/voice/sms levels to compare candidate plans against.

    Prefers their active plan's limits; falls back to 30-day usage when they have
    no completed recharge on file yet.
    """
    if current_plan is not None:
        return {
            "data_limit_mb": _normalize_limit(current_plan.get("data_limit_mb")),
            "voice_minutes": _normalize_limit(current_plan.get("voice_minutes")),
            "sms_count": _normalize_limit(current_plan.get("sms_count")),
        }
    return {
        "data_limit_mb": int(profile["total_data_mb"]),
        "voice_minutes": int(profile["total_voice_seconds"] // 60),
        "sms_count": int(profile["total_sms_count"]),
    }


def _build_plan_filter(baseline: dict[str, int], directions: dict[str, str | None]) -> str | None:
    """Build a Milvus metadata filter from stated more/less preferences.

    Skips an axis entirely if its baseline is already the unlimited sentinel and
    the subscriber wants "more" — no plan offers more than unlimited.
    """
    clauses = []
    for axis, direction in directions.items():
        if direction is None:
            continue
        field = _AXIS_FIELDS[axis]
        current = baseline[field]
        if direction == "more":
            if current >= _UNLIMITED_SENTINEL:
                continue
            clauses.append(f"{field} > {current}")
        else:
            clauses.append(f"{field} < {current}")
    return " and ".join(clauses) if clauses else None


def _preference_summary(directions: dict[str, str | None]) -> str:
    labels = {"data": "data", "voice": "calling minutes", "sms": "SMS"}
    parts = [f"{direction} {labels[axis]}" for axis, direction in directions.items() if direction is not None]
    return ", ".join(parts)


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

    cur_sms = current.get("sms_count")
    rec_sms_raw = rec_metadata.get("sms_count")
    rec_sms = None if rec_sms_raw == 0 else rec_sms_raw
    if cur_sms is not None and rec_sms is not None:
        diff = rec_sms - cur_sms
        if abs(diff) >= 20:
            label = "more" if diff > 0 else "fewer"
            parts.append(f"{abs(diff)} {label} SMS")
    elif rec_sms is None and cur_sms is not None:
        parts.append("unlimited SMS")

    price_diff_paise = rec_metadata.get("price", 0) - current.get("price_paise", 0)
    if price_diff_paise != 0:
        label = "more" if price_diff_paise > 0 else "less"
        parts.append(f"₹{abs(price_diff_paise) // 100} {label}")

    return " · ".join(parts) if parts else None


async def _run_recommend_plan(
    data_preference: str | None,
    voice_preference: str | None,
    sms_preference: str | None,
) -> dict:
    directions = {
        "data": _normalize_direction(data_preference),
        "voice": _normalize_direction(voice_preference),
        "sms": _normalize_direction(sms_preference),
    }
    if all(direction is None for direction in directions.values()):
        return {
            "needs_clarification": True,
            "question": "What would you like more or less of — data, calling minutes, or SMS?",
        }

    subscriber_id = current_subscriber_id()
    db = _require_db()

    async with db.transaction() as conn:
        profile = await get_subscriber_usage_profile(conn, UUID(subscriber_id))
        current_plan = await get_current_plan_details(conn, UUID(subscriber_id))

    baseline = _current_baseline(profile, current_plan)

    data_gb = profile["total_data_mb"] / 1024
    voice_min = profile["total_voice_seconds"] // 60
    query_text = f"data {profile['total_data_mb']:.0f}MB voice {voice_min}min sms {profile['total_sms_count']}"

    filter_expr = _build_plan_filter(baseline, directions)
    chunks = await _search_plans(query_text, top_k=10, filter_expr=filter_expr)
    if not chunks and filter_expr is not None:
        # The subscriber is already at (or past) the requested end of that axis for
        # every candidate plan — fall back to an unfiltered search so they still
        # see real options instead of an empty result.
        chunks = await _search_plans(query_text, top_k=10)

    summary = _preference_summary(directions)
    plans = []
    for c in chunks[:3]:
        price_paise = c.metadata.get("price", 0)
        plans.append(
            {
                "plan_id": c.metadata["plan_id"],
                "name": c.text.split()[0] if c.text else "",
                "price_paise": price_paise,
                "price_inr": f"₹{price_paise // 100}",
                "rationale": (
                    f"Based on your {data_gb:.1f}GB data usage this month and wanting {summary}, "
                    f"{c.text} at ₹{price_paise // 100}."
                ),
                "recharge_url": f"/subscriber/recharge?plan_id={c.metadata['plan_id']}",
                "comparison": _build_plan_comparison(current_plan, c.metadata),
            }
        )

    return {"plans": plans}


@tool
async def recommend_plan(
    data_preference: str | None = None,
    voice_preference: str | None = None,
    sms_preference: str | None = None,
) -> dict:
    """Recommend up to 3 plans matching what the subscriber wants more or less of.

    data_preference, voice_preference, sms_preference: each is 'more', 'less', or
    omitted. Provide at least one — set only the axes the subscriber actually
    stated a preference for; leave the rest as None. Preferences are compared
    against the subscriber's current plan limits (or their last 30 days of usage
    if they have no active plan on file). Returns
    ``{"needs_clarification": True, "question": "..."}`` when none of the three
    are given.
    """
    actual_subscriber_id = current_subscriber_id()
    return await _traced_tool(
        "recommend_plan",
        {
            "subscriber_id": actual_subscriber_id,
            "data_preference": data_preference,
            "voice_preference": voice_preference,
            "sms_preference": sms_preference,
        },
        lambda: _run_recommend_plan(data_preference, voice_preference, sms_preference),
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
async def ticket_create(cdr_reference: str, charge_paise: int) -> dict:
    """Create a billing-dispute support ticket for the authenticated subscriber (Story 5.8).

    Used at the end of the dispute multi-turn flow: the agent first presents the
    charge breakdown via ``charge_explain`` (Rating Agent A2A), the subscriber
    confirms the charge is wrong, then this tool creates the ticket.

    Parameters
    ----------
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
async def balance_lookup() -> dict:
    """Look up the subscriber's wallet balance via the Balance Management Agent (A2A) (Story 5.8).

    For the "what's my wallet balance?" intent the Support Agent invokes the
    Balance Management Agent graph (A2A) which reads the Valkey authoritative
    counter ``balance:{msisdn}``. The MSISDN is resolved server-side from the JWT.

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
