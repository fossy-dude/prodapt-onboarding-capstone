"""LLM-powered Rating Agent LangGraph for charge explanations.

The Support Agent invokes this separate same-process LangGraph through the
``charge_explain`` tool. In production the graph is a small ReAct loop: a rating
LLM reads the user's charge question, chooses rating tools for exact CDR lookup,
time-window search, and current balance checks, then returns a concise factual
summary. Subscriber identity is never supplied by the LLM; tools resolve it from
graph state through a contextvar set by the tool executor node.
"""

from __future__ import annotations

import contextvars
import dataclasses
import datetime as dt
import json
import logging
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from agents.support.tools import get_support_cache, get_support_db
from db.billing.queries import (
    get_charge_breakdown,
    get_charge_events_for_window,
    get_msisdn_for_subscriber,
    get_wallet_balance_from_db,
)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

MAX_RATING_REACT_STEPS = 6

_rating_subscriber_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rating_subscriber_id",
    default=None,
)


@dataclasses.dataclass
class ChargeBreakdown:
    """Structured charge breakdown data returned by Rating Agent."""

    cdr_id: str
    event_type: str
    duration_or_data: str
    rate_per_unit: int
    charge_paise: int
    balance_before: int
    balance_after: int


class RatingAgentState(TypedDict):
    """State for the LLM-powered Rating Agent graph."""

    subscriber_id: str
    user_query: str
    cdr_reference: NotRequired[str | None]
    result: ChargeBreakdown | None
    trace_id: str
    summary: NotRequired[str | None]
    rating_messages: NotRequired[list[BaseMessage]]
    react_steps: NotRequired[int]
    current_balance_paise: NotRequired[int | None]
    window_charges: NotRequired[list[dict]]
    lookup_error: NotRequired[str | None]


def _current_rating_subscriber_id() -> str:
    subscriber_id = _rating_subscriber_id.get()
    if not subscriber_id:
        raise RuntimeError("rating subscriber_id not bound")
    return subscriber_id


def _serialize_tool_output(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": repr(value)})


async def cdr_breakdown_tool(subscriber_id: str, cdr_reference: str) -> ChargeBreakdown | None:
    """Fetch a single CDR's rated charge breakdown for the authenticated subscriber."""
    db = get_support_db()
    if db is None:
        return None
    async with db.transaction() as conn:
        breakdown = await get_charge_breakdown(
            conn=conn,
            subscriber_id=subscriber_id,
            cdr_reference=cdr_reference,
        )
    return ChargeBreakdown(**breakdown) if breakdown is not None else None


async def current_balance_tool(subscriber_id: str) -> int | None:
    """Resolve current wallet balance, preferring Valkey and falling back to Postgres."""
    db = get_support_db()
    if db is None:
        return None
    async with db.transaction() as conn:
        msisdn = await get_msisdn_for_subscriber(conn, UUID(subscriber_id))
        if msisdn is not None:
            cache = get_support_cache()
            if cache is not None:
                balance = await cache.get_balance(msisdn)
                if balance is not None:
                    return int(balance)
        wallet = await get_wallet_balance_from_db(conn, UUID(subscriber_id))
    return int(wallet["balance_paise"]) if wallet is not None else None


async def charge_window_tool(
    subscriber_id: str,
    start_time: dt.datetime,
    end_time: dt.datetime,
    *,
    event_type: str | None = None,
) -> list[dict]:
    """Find rated CDR charge candidates in a time window."""
    db = get_support_db()
    if db is None:
        return []
    async with db.transaction() as conn:
        return await get_charge_events_for_window(
            conn,
            subscriber_id=subscriber_id,
            start_time=start_time,
            end_time=end_time,
            event_type=event_type,
        )


@tool
async def lookup_cdr_charge(cdr_reference: str) -> dict:
    """Look up one rated CDR charge by CDR reference UUID."""
    breakdown = await cdr_breakdown_tool(_current_rating_subscriber_id(), cdr_reference)
    if breakdown is None:
        return {"found": False, "breakdown": None}
    return {"found": True, "breakdown": dataclasses.asdict(breakdown)}


@tool
async def search_charge_window(start_time: str, end_time: str, event_type: str | None = None) -> dict:
    """Search rated CDR charges in an ISO-8601 time window, optionally filtered by voice/data/sms."""
    try:
        start_dt = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except ValueError as exc:
        return {"error": f"Invalid ISO-8601 time window: {exc}", "charges": []}
    charges = await charge_window_tool(
        _current_rating_subscriber_id(),
        start_dt,
        end_dt,
        event_type=event_type or None,
    )
    return {"charges": charges}


@tool
async def get_current_balance() -> dict:
    """Return the subscriber's current wallet balance in paise for charge context."""
    balance = await current_balance_tool(_current_rating_subscriber_id())
    return {"balance_paise": balance}


RATING_TOOLS = [lookup_cdr_charge, search_charge_window, get_current_balance]
_RATING_TOOL_BY_NAME = {tool_.name: tool_ for tool_ in RATING_TOOLS}


RATING_SYSTEM_PROMPT = (
    "You are a telecom billing Rating Agent. Explain why a charge happened using tools only; "
    "do not guess billing facts. Use lookup_cdr_charge when a CDR/reference UUID is present. "
    "If the user gives a date/time or time range instead of a reference, use search_charge_window. "
    "Use get_current_balance when the balance impact or current wallet context is relevant. "
    "Return a concise answer: what was charged, when/for what usage, amount, balance impact, "
    "and whether more information is needed. Never reveal PII."
)


def _initial_rating_messages(state: RatingAgentState) -> list[BaseMessage]:
    query = state.get("user_query") or "Explain this charge."
    cdr_reference = state.get("cdr_reference")
    if cdr_reference:
        query = f"{query}\nKnown CDR reference: {cdr_reference}"
    now_iso = dt.datetime.now(dt.UTC).isoformat()
    system_content = f"{RATING_SYSTEM_PROMPT}\n\nCurrent date/time (UTC): {now_iso}"
    return [SystemMessage(content=system_content), HumanMessage(content=query)]


def _breakdown_from_tool_messages(messages: list[BaseMessage]) -> ChargeBreakdown | None:
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.name != "lookup_cdr_charge":
            continue
        try:
            payload = json.loads(str(message.content))
        except (TypeError, ValueError):
            continue
        breakdown = payload.get("breakdown") if isinstance(payload, dict) else None
        if isinstance(breakdown, dict):
            try:
                return ChargeBreakdown(**breakdown)
            except TypeError:
                return None
    return None


async def rating_agent_node(state: RatingAgentState, *, llm: Any) -> RatingAgentState:
    """Invoke the tool-bound rating LLM for the next reasoning step."""
    messages = state.get("rating_messages") or _initial_rating_messages(state)
    response = await llm.ainvoke(messages)
    return {
        **state,
        "rating_messages": [*messages, response],
        "react_steps": int(state.get("react_steps", 0)) + 1,
    }


async def rating_tools_node(state: RatingAgentState) -> RatingAgentState:
    """Execute Rating Agent tool calls with subscriber identity injected from state."""
    messages = state.get("rating_messages") or []
    if not messages:
        return state
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return state

    token = _rating_subscriber_id.set(state["subscriber_id"])
    tool_messages: list[ToolMessage] = []
    try:
        for call in tool_calls:
            name = call.get("name")
            tool_call_id = call.get("id") or name or "rating_tool_call"
            selected_tool = _RATING_TOOL_BY_NAME.get(name or "")
            if selected_tool is None:
                output: Any = {"error": f"Unknown rating tool: {name}"}
            else:
                output = await selected_tool.ainvoke(call.get("args") or {})
            tool_messages.append(
                ToolMessage(
                    content=_serialize_tool_output(output),
                    name=name or "unknown_tool",
                    tool_call_id=tool_call_id,
                )
            )
    finally:
        _rating_subscriber_id.reset(token)

    updated_messages = [*messages, *tool_messages]
    result = state.get("result") or _breakdown_from_tool_messages(updated_messages)
    latest_balance = state.get("current_balance_paise")
    for message in reversed(tool_messages):
        if message.name != "get_current_balance":
            continue
        try:
            payload = json.loads(str(message.content))
        except (TypeError, ValueError):
            break
        latest_balance = payload.get("balance_paise") if isinstance(payload, dict) else latest_balance
        break
    return {
        **state,
        "rating_messages": updated_messages,
        "result": result,
        "current_balance_paise": latest_balance,
    }


async def synthesize_explanation(state: RatingAgentState) -> RatingAgentState:
    """Copy the final rating LLM response into ``summary`` and preserve structured result."""
    messages = state.get("rating_messages") or []
    summary = state.get("summary")
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            summary = str(message.content)
            break
    return {**state, "summary": summary, "result": state.get("result")}


async def deterministic_rating_node(state: RatingAgentState) -> RatingAgentState:
    """Fallback graph used only before production wires an LLM into the rating graph."""
    cdr_reference = state.get("cdr_reference")
    result = await cdr_breakdown_tool(state["subscriber_id"], cdr_reference) if cdr_reference else None
    if result is None:
        summary = (
            "I could not find a rated charge from the supplied details. Please provide the CDR reference or date/time."
        )
    else:
        amount = result.charge_paise / 100
        summary = f"This was a {result.event_type} charge of ₹{amount:.2f} for {result.duration_or_data}."
    return {**state, "result": result, "summary": summary}


def _route_after_agent(state: RatingAgentState) -> str:
    messages = state.get("rating_messages") or []
    if not messages or int(state.get("react_steps", 0)) >= MAX_RATING_REACT_STEPS:
        return "synthesize_explanation"
    last = messages[-1]
    return "rating_tools" if getattr(last, "tool_calls", None) else "synthesize_explanation"


def build_rating_graph(llm: BaseChatModel | None = None) -> CompiledStateGraph:
    """Build the Rating Agent graph, LLM-powered when ``llm`` is supplied."""
    graph = StateGraph(RatingAgentState)  # type: ignore[bad-specialization]

    if llm is None:
        graph.add_node("deterministic_rating_node", deterministic_rating_node)
        graph.set_entry_point("deterministic_rating_node")
        graph.set_finish_point("deterministic_rating_node")
        return graph.compile()

    llm_with_tools = llm.bind_tools(RATING_TOOLS)

    async def _agent_node(state: RatingAgentState) -> RatingAgentState:
        return await rating_agent_node(state, llm=llm_with_tools)

    graph.add_node("rating_agent", _agent_node)
    graph.add_node("rating_tools", rating_tools_node)
    graph.add_node("synthesize_explanation", synthesize_explanation)
    graph.set_entry_point("rating_agent")
    graph.add_conditional_edges("rating_agent", _route_after_agent, ["rating_tools", "synthesize_explanation"])
    graph.add_edge("rating_tools", "rating_agent")
    graph.set_finish_point("synthesize_explanation")
    return graph.compile()


rating_graph = build_rating_graph()


def set_rating_graph(graph: CompiledStateGraph) -> None:
    """Replace the process-wide Rating Agent graph used by ``charge_explain``."""
    global rating_graph
    rating_graph = graph


__all__ = [
    "RATING_TOOLS",
    "ChargeBreakdown",
    "RatingAgentState",
    "build_rating_graph",
    "cdr_breakdown_tool",
    "charge_window_tool",
    "current_balance_tool",
    "deterministic_rating_node",
    "get_current_balance",
    "lookup_cdr_charge",
    "rating_agent_node",
    "rating_graph",
    "rating_tools_node",
    "search_charge_window",
    "set_rating_graph",
    "synthesize_explanation",
]
