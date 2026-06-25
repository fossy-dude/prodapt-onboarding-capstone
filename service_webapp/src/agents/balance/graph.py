"""Balance Management Agent LangGraph (Story 5.8 AC #5, #6; architecture §1.6.1).

A deterministic single-node A2A agent. The Support Agent's ``balance_lookup`` tool
(see :mod:`agents.support.tools`) invokes this graph so the Valkey wallet read is
traced as an *independent* A2A call (FR-72) rather than a plain tool call.

This is the A2A wrapper distinct from the Support Agent's direct ``get_balance``
tool (architecture §1.6.1): for the "what's my wallet balance?" intent the agent
routes through this graph so the read is observable as a child span named
``a2a_balance_agent`` nested under the Support Agent trace. No LLM — it is a
thin, traceable wrapper over the cache read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from langgraph.graph import StateGraph

from agents.support.tools import get_support_cache
from core.security import mask_msisdn

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


class BalanceAgentState(TypedDict):
    """State for the Balance Management Agent.

    Attributes
    ----------
    msisdn : str
        Subscriber MSISDN whose ``balance:{msisdn}`` counter is read.
    balance_paise : int | None
        Resolved balance in paise. ``None`` only when the cache is not wired; a
        cold key (no Valkey entry) resolves to ``0``.
    trace_id : str
        LangFuse trace id passed from the Support Agent for nested span tracing.
    """

    msisdn: str
    balance_paise: int | None
    trace_id: str


async def fetch_balance(state: BalanceAgentState) -> BalanceAgentState:
    """Read ``balance:{msisdn}`` from Valkey and set ``balance_paise``.

    The cache singleton (set at FastAPI startup via :func:`set_support_adapters`)
    abstracts the ``balance:`` key prefix. A cold cache (no key seeded) yields
    ``0`` — a freshly-provisioned subscriber with no CDR activity has a zero
    wallet — rather than ``None``. ``None`` is reserved for the cache-not-wired
    (degraded) case so the caller can explain the balance is unavailable.
    """
    msisdn = state["msisdn"]
    cache = get_support_cache()
    if cache is None:
        logger.debug("balance_agent: cache not wired — returning None for msisdn=%s", mask_msisdn(msisdn))
        state["balance_paise"] = None
        return state
    balance = await cache.get_balance(msisdn)
    state["balance_paise"] = int(balance) if balance is not None else 0
    return state


def build_balance_graph() -> CompiledStateGraph:
    """Build and compile the Balance Management Agent graph.

    Single-node deterministic graph: ``fetch_balance`` → END.
    """
    # CopilotKitState/TypedDict state — pyrefly's langgraph stubs don't recognise
    # the TypedDict as a valid StateT at static-analysis time (runtime is correct).
    graph = StateGraph(BalanceAgentState)  # type: ignore[bad-specialization]
    graph.add_node("fetch_balance", fetch_balance)
    graph.set_entry_point("fetch_balance")
    graph.set_finish_point("fetch_balance")
    return graph.compile()


# Singleton graph instance for A2A calls (mirrors ``rating_graph`` in Story 5.7).
balance_graph = build_balance_graph()


__all__ = ["BalanceAgentState", "balance_graph", "build_balance_graph", "fetch_balance"]
