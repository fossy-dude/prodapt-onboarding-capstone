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
from typing import TYPE_CHECKING, Any

from copilotkit.langgraph import CopilotKitState
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agents.guardrails.validator import log_rejection
from agents.support.identity import current_msisdn, current_session_id
from agents.support.tools import SUPPORT_TOOLS, get_support_db
from core.config import settings
from core.observability.langfuse import get_langfuse_client, set_trace_usage
from core.security import mask_msisdn

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

    from agents.guardrails.validator import GuardrailResult, InputGuardrail

logger = logging.getLogger(__name__)

__all__ = ["SUPPORT_SYSTEM_PROMPT", "SupportAgentState", "build_support_graph", "set_guardrail"]

# ReAct loop ceiling (patch 6): guard against unbounded tool-call cycles.
# StateGraph.compile() does not accept recursion_limit, so the cap is enforced
# via a per-turn counter incremented in ``support_agent_node`` and checked in
# ``_route_after_agent``.
MAX_REACT_STEPS = 6

# ARCH-32: billing/account scope, TRAI compliance, PII ceiling (last-4 only).
SUPPORT_SYSTEM_PROMPT = (
    "You are a billing and account assistant for an MVNO. "
    "Answer only billing, plan, usage, and account queries. "
    "Always call a tool to fetch real data — never guess balances, quotas, usage figures, or plan details. "
    "Follow TRAI regulations. Never reveal PII beyond the MSISDN last-4 digits.\n\n"
    "Tool usage guide:\n"
    "- Subscriber asks about their current plan, validity, or quotas → call get_plan\n"
    "- Subscriber asks what plans are available, wants to see options → call list_plans\n"
    "- Subscriber asks for a recommendation, best plan for them, or which plan to recharge with → call recommend_plan\n"
    "  (omit preference unless they stated one: 'data', 'voice', or 'value')\n"
    "  If recommend_plan returns needs_clarification=true, ask the subscriber their preference then call recommend_plan again with that preference.\n"
    "- Subscriber wants to recharge with a specific plan → call recharge_flow with the plan_id\n"
    "- Subscriber asks about their balance → call get_balance\n"
    "- Subscriber asks how much data/calls/SMS they have used → call get_usage\n"
    "- Subscriber asks to explain a specific charge or says a charge looks wrong → ask for the CDR reference ID, then call charge_explain\n"
    "- Subscriber wants to dispute a charge after seeing the breakdown → call ticket_create\n"
    "- Subscriber asks a general question about plans, coverage, or policies → call rag_search_tool\n"
)


class SupportAgentState(CopilotKitState):
    """LangGraph state for the Support Agent.

    Extends CopilotKitState (which already carries ``messages`` and the CopilotKit
    AG-UI fields). The checkpointer persists this full state between turns —
    no manual Valkey context loading needed.
    """

    session_id: str
    msisdn: str
    rejected: bool  # Set by guardrail_node when input validation fails
    react_steps: int  # ReAct turns taken this run; capped by MAX_REACT_STEPS


# ── Guardrail singleton (Story 5.5) ──────────────────────────────────────────────
# Module-level guardrail instance set once at FastAPI startup, so guardrail_node
# can access it without dependency injection through the LangGraph registry.
_guardrail: InputGuardrail | None = None


def set_guardrail(guardrail: InputGuardrail | None) -> None:
    """Set (or clear with ``None``) the process-wide guardrail singleton."""
    global _guardrail
    _guardrail = guardrail


async def guardrail_node(state: dict) -> dict:
    """Validate incoming user message before processing by the agent.

    Extracts the latest user message from state.messages and validates it via
    the guardrail singleton. If validation fails, appends an assistant message
    with the rejection response and sets the ``rejected`` flag to short-circuit
    the graph (route to END via :func:`_route_after_guardrail`).

    Returns
    -------
        Updated state with ``rejected`` flag and optional rejection message
    """
    messages = state.get("messages", [])
    if not messages:
        return {"rejected": False}

    # Only validate genuine user turns; skip tool results / assistant messages.
    latest_message = messages[-1]
    if not isinstance(latest_message, HumanMessage):
        return {"rejected": False}
    message_content = getattr(latest_message, "content", "")
    if isinstance(message_content, list):
        # Multimodal content blocks — concatenate the text parts.
        message_content = " ".join(block.get("text", "") for block in message_content if isinstance(block, dict))
    if not isinstance(message_content, str):
        message_content = str(message_content)

    # Default to pass if no guardrail is configured (degraded graceful)
    if _guardrail is None:
        logger.warning("guardrail_node called but no guardrail singleton set - passing message")
        return {"rejected": False}

    # Validate the message
    result: GuardrailResult = await _guardrail.validate(message_content)

    if not result.passed:
        # Rejection: append assistant message with rejection response
        rejection_message = result.response_message or "I cannot process this request."
        updated_messages = messages + [AIMessage(content=rejection_message)]

        # AC #4: persist the rejection (SHA-256 hash only) for audit. Best-effort —
        # a logging failure must never break the user-facing rejection.
        session_id = current_session_id()
        db = get_support_db()
        if session_id and db is not None:
            try:
                await log_rejection(
                    db,
                    session_id,
                    result.rejection_reason or "UNKNOWN",
                    message_content,
                )
            except Exception as exc:
                logger.warning("guardrail_node: log_rejection failed: %s", exc)
        elif session_id:
            logger.info("Guardrail rejection (no DB wired): reason=%s", result.rejection_reason)

        return {
            "messages": updated_messages,
            "rejected": True,
            "react_steps": 0,
        }

    # Passed: reset the per-run ReAct counter so it doesn't accumulate across turns.
    return {"rejected": False, "react_steps": 0}


def _route_after_guardrail(state: dict) -> str:
    """Route after guardrail validation.

    If ``rejected`` is True, route to END (short-circuit before LLM call).
    Otherwise, route to ``support_agent_node`` for normal processing.
    """
    return END if state.get("rejected") else "support_agent_node"


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
        "session_id": current_session_id(),
        "msisdn": mask_msisdn(current_msisdn()),
        "message_count": len(messages),
    }


# Deterministic reply when the model is unavailable (patch 3). Surfacing a raw
# exception to the CopilotKit runtime would 500 the chat turn; a graceful reply
# keeps the conversation usable during a model outage / rate-limit.
_FALLBACK_REPLY = AIMessage(
    content="I'm having trouble reaching the billing service right now. Please try again in a moment.",
)


async def _invoke_llm(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    state: dict,
) -> BaseMessage:
    """Invoke the tool-bound LLM under a LangFuse span (patch 2/3).

    Observability is best-effort: a LangFuse failure never breaks the business
    call, and an LLM failure returns :data:`_FALLBACK_REPLY` instead of raising
    into the CopilotKit runtime.
    """
    client = get_langfuse_client()
    if client is None:
        try:
            return await llm.ainvoke(messages)
        except Exception as exc:  # model outage / rate-limit
            logger.warning("support_agent_node LLM invoke failed (no trace): %s", exc)
            return _FALLBACK_REPLY

    try:
        with client.start_as_current_observation(
            name="support_agent_node",
            as_type="generation",
            input=_redacted_snapshot(state),
            model=settings.chat_deployment_mini,
        ) as observation:
            try:
                response = await llm.ainvoke(messages)
            except Exception as exc:
                logger.warning("support_agent_node LLM invoke failed: %s", exc)
                return _FALLBACK_REPLY
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
            return response
    except Exception as exc:  # span open failed; fall back to a plain invoke
        logger.warning("LangFuse support_agent_node span open failed: %s", exc)
        try:
            return await llm.ainvoke(messages)
        except Exception as exc2:
            logger.warning("support_agent_node LLM invoke failed (after span err): %s", exc2)
            return _FALLBACK_REPLY


async def support_agent_node(state: dict, *, llm: BaseChatModel) -> dict:
    """Supervisor turn: invoke tool-bound LLM and return the response.

    The checkpointer restores the full message history into ``state["messages"]``
    before this node runs — no manual context loading needed. Returns
    ``{"messages": [response]}`` for LangGraph to merge into state. Tool calls in
    the response route to the ``tools`` node via :func:`_route_after_agent`.
    """
    messages: list[BaseMessage] = [SystemMessage(content=SUPPORT_SYSTEM_PROMPT)]
    messages.extend(state.get("messages", []))

    response = await _invoke_llm(llm, messages, state)

    return {
        "messages": [response],
        "react_steps": int(state.get("react_steps", 0)) + 1,
    }


def _route_after_agent(state: dict) -> str:
    """Route to the tool executor when the agent emitted tool calls, else finish."""
    messages = state.get("messages", [])
    if not messages:
        return END
    # ReAct loop guard (patch 6): stop dispatching to tools once the turn
    # counter hits the ceiling, so a runaway tool-call cycle can never exhaust
    # the graph.
    if int(state.get("react_steps", 0)) >= MAX_REACT_STEPS:
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

    Story 5.5: Guardrail node is now the entry point, validating all incoming
    messages before they reach the agent. Rejected messages short-circuit to END.
    """
    llm_with_tools = llm.bind_tools(SUPPORT_TOOLS)

    async def _node(state: dict) -> dict:
        return await support_agent_node(state, llm=llm_with_tools)

    # Tool execution is wrapped in a LangFuse span (patch 4) so DB/Valkey tool
    # latency is observable independently of the LLM call. Observability is
    # best-effort and never blocks tool execution.
    tool_executor = ToolNode(SUPPORT_TOOLS)

    async def _tools_node(state: dict) -> dict:
        client = get_langfuse_client()
        if client is None:
            return await tool_executor.ainvoke(state)
        try:
            with client.start_as_current_observation(
                name="support_tools",
                as_type="generation",
                input=_redacted_snapshot(state),
            ) as observation:
                result = await tool_executor.ainvoke(state)
                try:
                    observation.update(output={"status": "tools_executed"})
                except Exception:
                    pass
                return result
        except Exception as exc:
            logger.warning("LangFuse support_tools span open failed: %s", exc)
            return await tool_executor.ainvoke(state)

    # CopilotKitState is a TypedDict; pyrefly's langgraph stubs don't recognise
    # the CopilotKit-mixin TypedDict as a valid StateT bound at static-analysis
    # time. Runtime is correct (CopilotKit's own examples construct it this way).
    builder = StateGraph(SupportAgentState)  # type: ignore[bad-specialization]

    # Add nodes (Story 5.5: guardrail_node is first)
    builder.add_node("guardrail_node", guardrail_node)
    builder.add_node("support_agent_node", _node)
    builder.add_node("tools", _tools_node)

    # Story 5.5: Entry point is now guardrail_node (not support_agent_node)
    builder.set_entry_point("guardrail_node")

    # Story 5.5: Conditional routing after guardrail
    # If rejected → END (short-circuit), else → support_agent_node
    builder.add_conditional_edges("guardrail_node", _route_after_guardrail, ["support_agent_node", END])

    # Existing ReAct loop: agent → tools → agent
    builder.add_conditional_edges("support_agent_node", _route_after_agent, ["tools", END])
    builder.add_edge("tools", "support_agent_node")

    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)
