"""Rating Agent LangGraph for charge breakdown explanation (Story 5.7).

This is a deterministic, single-node agent that fetches billing information
from Postgres and returns structured charge breakdown data. No LLM calls.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, TypedDict

from langgraph.graph import StateGraph

from agents.support.tools import get_support_db
from db.billing.queries import get_charge_breakdown

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


@dataclasses.dataclass
class ChargeBreakdown:
    """Structured charge breakdown data returned by Rating Agent.

    Attributes
    ----------
    cdr_id : str
        The CDR reference ID (UUID).
    event_type : str
        Event type: 'voice', 'data', or 'sms'.
    duration_or_data : str
        Human-readable duration or data volume (e.g., "5m 30s", "123.45MB").
    rate_per_unit : int
        Rate per unit in paise (e.g., paise per minute for voice).
    charge_paise : int
        Total charge for this event in paise.
    balance_before : int
        Balance before the charge in paise.
    balance_after : int
        Balance after the charge in paise.
    """

    cdr_id: str
    event_type: str
    duration_or_data: str
    rate_per_unit: int
    charge_paise: int
    balance_before: int
    balance_after: int


class RatingAgentState(TypedDict):
    """State for Rating Agent LangGraph.

    Attributes
    ----------
    subscriber_id : str
        Subscriber UUID (passed from Support Agent).
    cdr_reference : str
        CDR ID to fetch breakdown for (passed from Support Agent).
    result : ChargeBreakdown | None
        Structured breakdown result (None if CDR not found).
    trace_id : str
        LangFuse trace ID for nested span tracing.
    """

    subscriber_id: str
    cdr_reference: str
    result: ChargeBreakdown | None
    trace_id: str


async def fetch_breakdown(state: RatingAgentState) -> RatingAgentState:
    """Fetch charge breakdown from billing_audit_log and plan configuration.

    This node queries the billing CDR events and plan configuration to
    retrieve structured charge breakdown information.

    Parameters
    ----------
    state : RatingAgentState
        Current agent state with subscriber_id and cdr_reference.

    Returns
    -------
    RatingAgentState
        Updated state with result populated (ChargeBreakdown or None).
    """
    subscriber_id = state["subscriber_id"]
    cdr_reference = state["cdr_reference"]

    # Get database from support tools singleton (set at FastAPI startup)
    db = get_support_db()
    if db is None:
        # Database not configured — return None (degraded graceful)
        state["result"] = None
        return state

    async with db.transaction() as conn:
        breakdown = await get_charge_breakdown(
            conn=conn,
            subscriber_id=subscriber_id,
            cdr_reference=cdr_reference,
        )

    state["result"] = ChargeBreakdown(**breakdown) if breakdown is not None else None
    return state


def build_rating_graph() -> CompiledStateGraph:
    """Build and compile the Rating Agent LangGraph.

    The Rating Agent is a single-node deterministic graph:
    - Input: subscriber_id, cdr_reference, trace_id
    - Process: fetch_breakdown node (DB query)
    - Output: ChargeBreakdown or None

    Returns
    -------
    CompiledStateGraph
        Compiled LangGraph ready for invocation.
    """
    # TypedDict state — pyrefly's langgraph stubs don't recognise the TypedDict as
    # a valid StateT at static-analysis time (runtime is correct).
    graph = StateGraph(RatingAgentState)  # type: ignore[bad-specialization]

    # Add the single node
    graph.add_node("fetch_breakdown", fetch_breakdown)

    # Set entry point
    graph.set_entry_point("fetch_breakdown")

    # Connect to END
    graph.set_finish_point("fetch_breakdown")

    return graph.compile()


# Singleton graph instance for A2A calls
rating_graph = build_rating_graph()


__all__ = [
    "ChargeBreakdown",
    "RatingAgentState",
    "build_rating_graph",
    "rating_graph",
]
