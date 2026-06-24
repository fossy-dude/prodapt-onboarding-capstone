"""Support Agent LangGraph graph (Story 5.4 AC #1, #2, #5; architecture §1.6.1).

A single supervisor node (tool-calling LLM) plus a ``ToolNode`` executor wired in
a ReAct loop:

    ┌─────────────────────┐  has tool_calls   ┌────────┐
    │ support_agent_node  │ ───────────────▶  │ tools  │
    │  (LLM + context +   │ ◀──────────────── │ (exec) │
    │   LangFuse trace)   │        back        └────────┘
    └─────────────────────┘
            │  no tool_calls
            ▼
           END

* State extends :class:`copilotkit.langgraph.CopilotKitState` so AG-UI
  ``StateSnapshot`` events fire on transitions (architecture §1.6.1).
* Each turn loads the prior Valkey context (Story 5.4 AC #3), invokes the
  ``chat_deployment_mini`` model bound to the support tools, and persists the
  exchange back to Valkey.
* Every node execution is traced to LangFuse with a **PII-redacted** snapshot
  (ARCH-32: only ``msisdn[-4:]``, never raw MSISDN/name/address), the model name
  and token usage (FR-72).

CopilotKit SDK note: the installed ``copilotkit`` exposes ``LangGraphAGUIAgent``
(not ``LangGraphAgent``) and ``CopilotKitRemoteEndpoint`` (``CopilotKitSDK`` is
deprecated) — see ``routers/chat.py``.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from copilotkit.langgraph import CopilotKitState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agents.support.context import load_context, save_turn
from agents.support.tools import SUPPORT_TOOLS, get_support_cache
from core.config import settings
from core.observability.langfuse import get_langfuse_client, set_trace_usage
from core.security import mask_msisdn

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

__all__ = ["SUPPORT_SYSTEM_PROMPT", "SupportAgentState", "build_support_graph"]

# ARCH-32: billing/account scope, TRAI compliance, PII ceiling (last-4 only).
SUPPORT_SYSTEM_PROMPT = (
    "You are a billing and account assistant for an MVNO. "
    "Answer only billing, plan, usage, and account queries. "
    "Use the provided tools to fetch real data — never guess balances, quotas or "
    "usage figures. Follow TRAI regulations. "
    "Never reveal PII beyond the MSISDN last-4 digits."
)


class SupportAgentState(CopilotKitState):
    """LangGraph state for the Support Agent.

    Extends CopilotKitState (which already carries ``messages`` and the CopilotKit
    AG-UI fields) with the subscriber identity needed to scope tool calls and the
    session id used to key the Valkey conversation context.
    """

    session_id: str
    msisdn: str
    context_turns: list[dict]


def _usage_from_response(response: BaseMessage) -> dict[str, int] | None:
    """Extract a ``{input, output, total}`` token-usage dict from an LLM response.

    Modern langchain models populate ``usage_metadata``; ``None`` when absent so
    the caller omits usage from the trace rather than recording zeros.
    """
    meta = getattr(response, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    return {
        "input": int(meta.get("input_tokens", 0)),
        "output": int(meta.get("output_tokens", 0)),
        "total": int(meta.get("total_tokens", 0)),
    }


def _redacted_snapshot(state: dict) -> dict[str, Any]:
    """Build a PII-safe snapshot of the node state for the LangFuse trace input.

    ARCH-32 / §1.11.6: only the masked MSISDN and message counts are recorded —
    never raw MSISDN, name or address. The full message bodies are intentionally
    omitted (they may echo subscriber PII).
    """
    messages = state.get("messages", [])
    return {
        "session_id": state.get("session_id"),
        "msisdn": mask_msisdn(state.get("msisdn", "")),
        "message_count": len(messages),
        "has_context_turns": len(state.get("context_turns", [])),
    }


def _prior_context_messages(turns: list[dict]) -> list[BaseMessage]:
    """Render Valkey-loaded prior turns into langchain messages."""
    msgs: list[BaseMessage] = []
    for turn in turns:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
    return msgs


async def support_agent_node(state: dict, *, llm: BaseChatModel) -> dict:
    """Supervisor turn: load context → invoke tool-bound LLM → persist → trace.

    Returns ``{"messages": [response]}`` for LangGraph to merge. Tool calls in the
    response route to the ``tools`` node via :func:`_route_after_agent`.
    """
    session_id = state.get("session_id", "")
    msisdn = state.get("msisdn", "")

    # AC #3: prepend Valkey-persisted prior turns so the agent has memory across
    # CopilotKit requests / frontend reloads. Degrades to no context if the cache
    # is not wired (graph should not be reachable then, but stay safe).
    cache = get_support_cache()
    prior_turns: list[dict] = []
    if cache is not None and session_id:
        prior_turns = await load_context(cache, session_id)

    messages: list[BaseMessage] = [SystemMessage(content=SUPPORT_SYSTEM_PROMPT)]
    messages.extend(_prior_context_messages(prior_turns))
    messages.extend(state.get("messages", []))

    client = get_langfuse_client()
    response: BaseMessage
    if client is None:
        response = await llm.ainvoke(messages)
    else:
        # FR-72 + ARCH-32: one LangFuse generation per node run, PII-redacted.
        try:
            observation_cm = client.start_as_current_observation(
                name="support_agent_node",
                as_type="generation",
                input=_redacted_snapshot(state),
                model=settings.chat_deployment_mini,
            )
            observation = observation_cm.__enter__()
        except Exception as exc:  # observability must never break the business call
            logger.warning("LangFuse support_agent_node span open failed: %s", exc)
            response = await llm.ainvoke(messages)
        else:
            try:
                response = await llm.ainvoke(messages)
                usage = _usage_from_response(response)
                if usage is not None:
                    set_trace_usage(usage)
                update_kwargs: dict[str, Any] = {
                    "output": {"has_tool_calls": bool(getattr(response, "tool_calls", None))},
                }
                if usage is not None:
                    update_kwargs["usage_details"] = usage
                try:
                    observation.update(**update_kwargs)
                except Exception as exc:
                    logger.warning("LangFuse support_agent_node span update failed: %s", exc)
            finally:
                try:
                    observation_cm.__exit__(*sys.exc_info())
                except Exception:
                    pass

    # AC #3: persist this exchange (user ask + agent reply) to Valkey. We persist
    # the inbound user message and the assistant text; tool-call rounds are an
    # internal detail and are not stored.
    if cache is not None and session_id:
        inbound = state.get("messages", [])
        last_user = next(
            (m for m in reversed(inbound) if isinstance(m, HumanMessage)),
            None,
        )
        if last_user is not None:
            await save_turn(cache, session_id, "user", str(last_user.content))
        if isinstance(response, AIMessage) and not getattr(response, "tool_calls", None):
            await save_turn(cache, session_id, "assistant", str(response.content))

    return {"messages": [response]}


def _route_after_agent(state: dict) -> str:
    """Route to the tool executor when the agent emitted tool calls, else finish."""
    messages = state.get("messages", [])
    if not messages:
        return END
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        return "tools"
    return END


def build_support_graph(llm: BaseChatModel) -> CompiledStateGraph:
    """Compile the Support Agent ReAct graph bound to ``llm``.

    The supervisor closure captures the tool-bound LLM; the ``tools`` node is a
    standard langgraph :class:`ToolNode` over :data:`SUPPORT_TOOLS`.
    """

    async def _node(state: dict) -> dict:
        return await support_agent_node(state, llm=llm)

    builder = StateGraph(SupportAgentState)
    builder.add_node("support_agent_node", _node)
    builder.add_node("tools", ToolNode(SUPPORT_TOOLS))
    builder.set_entry_point("support_agent_node")
    builder.add_conditional_edges("support_agent_node", _route_after_agent, ["tools", END])
    builder.add_edge("tools", "support_agent_node")
    return builder.compile()
