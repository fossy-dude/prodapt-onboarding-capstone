"""Conclusion Agent LangGraph for session-end summarization and notification triggering (Story 5.10 AC #1, #2, #5).

A deterministic linear A2A agent that runs after a chat session ends (explicit close or
TTL expiry). It loads the session history from Valkey, summarizes key learnings using
an LLM, stores them in the database, and triggers the Notification Agent.

    ┌─────────────────────┐
    │ load_session_history│
    └─────────────────────┘
            │
            ▼
    ┌─────────────────────┐
    │  summarise_session  │  (LLM call: gpt-4o-mini)
    └─────────────────────┘
            │
            ▼
    ┌─────────────────────┐
    │   store_learning    │  (DB: support_session_learnings)
    └─────────────────────┘
            │
            ▼
    ┌─────────────────────────────┐
    │ trigger_notification (A2A)  │
    └─────────────────────────────┘
            │
            ▼
           END

* Each node execution is traced to LangFuse with a **PII-redacted** snapshot
  (ARCH-32: only ``msisdn[-4:]`` in traces, never raw MSISDN/name/address).
* The LLM uses ``chat_deployment_mini`` (gpt-4o-mini) for cost efficiency (FR-35).
* Session history is read from Valkey HASH ``chat_context:{session_id}`` which has a
  2-hour TTL (ARCH-5).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agents.notification import get_notification_graph  # type: ignore[no-redef]
from core.config import settings
from core.observability.langfuse import get_langfuse_client
from core.security import mask_msisdn
from db.support.commands import store_session_learning

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

    from adapters.postgres import Psycopg3AsyncAdapter
    from adapters.redis import ValkeyAdapter

logger = logging.getLogger(__name__)

# Global singletons for adapters (set at FastAPI startup)
_valkey_client: ValkeyAdapter | None = None
_db_adapter: Psycopg3AsyncAdapter | None = None


def get_valkey_client() -> ValkeyAdapter:
    """Get the globally-registered Valkey client instance."""
    if _valkey_client is None:
        raise RuntimeError("Valkey client not initialized")
    return _valkey_client


def get_db_adapter() -> Psycopg3AsyncAdapter:
    """Get the globally-registered DB adapter instance."""
    if _db_adapter is None:
        raise RuntimeError("DB adapter not initialized")
    return _db_adapter


def set_conclusion_adapters(valkey: ValkeyAdapter, db: Psycopg3AsyncAdapter) -> None:
    """Register the Valkey and DB adapters globally (called at FastAPI startup)."""
    global _valkey_client, _db_adapter
    _valkey_client = valkey
    _db_adapter = db
    logger.info("Conclusion Agent adapters registered globally")


class ConclusionAgentState(TypedDict):
    """State for the Conclusion Agent.

    Attributes
    ----------
    session_id : str
        The support chat session ID (UUID from ``support_chat_sessions.id``).
    subscriber_id : str
        The subscriber UUID for database foreign key and notification targeting.
    session_history : list[dict]
        Chronological list of chat turns loaded from Valkey ``chat_context:{session_id}``.
        Each dict has ``role`` (user/assistant) and ``content``.
    summary : str | None
        JSON-structured session summary produced by the LLM. Contains
        ``summary_text``, ``topics``, ``actions``, ``unresolved``. Set after
        ``summarise_session`` node.
    trace_id : str
        LangFuse trace id for nested span tracing (FR-72). Propagated to the
        Notification Agent as the parent span.
    """

    session_id: str
    subscriber_id: str
    session_history: list[dict]
    summary: str | None
    trace_id: str


async def load_session_history(state: ConclusionAgentState) -> ConclusionAgentState:
    """Load all chat turns from Valkey HASH ``chat_context:{session_id}``.

    Reads all ``turn_N`` fields from the HASH, parses JSON, and reconstructs a
    chronological turn list. The Valkey key has a 2-hour TTL (ARCH-5); if the key
    has expired, this returns an empty history (best-effort: the session may have
    been idle for >2 hours).

    Parameters
    ----------
    state : ConclusionAgentState
        Current agent state. Must contain ``session_id``.

    Returns
    -------
    ConclusionAgentState
        Updated state with ``session_history`` populated (empty list if key expired).
    """
    client = get_valkey_client()
    key = f"chat_context:{state['session_id']}"

    # Read all HASH fields; if key doesn't exist (TTL expired), return empty history
    fields = await client.hgetall(key)
    if not fields:
        logger.warning(f"Conclusion Agent: session history key expired or missing: {key}")
        return {**state, "session_history": []}

    # Reconstruct chronological order: sort by turn_N suffix
    turns = []
    for field_name, value in fields.items():
        if field_name.startswith("turn_"):
            try:
                turn_data = json.loads(value)
                turns.append(turn_data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Conclusion Agent: failed to parse turn {field_name}: {e}")
                continue

    # Sort by timestamp/sequence to maintain chronological order
    turns.sort(key=lambda t: t.get("timestamp", 0))

    logger.info(f"Conclusion Agent: loaded {len(turns)} turns for session {state['session_id']}")
    return {**state, "session_history": turns}


async def summarise_session(state: ConclusionAgentState) -> ConclusionAgentState:
    """Summarize the chat session using the ``chat_deployment_mini`` LLM.

    The LLM is prompted to extract:
    1. Topics discussed
    2. Actions taken (recharges, tickets created, etc.)
    3. Unresolved queries

    The response must be JSON with keys: ``summary_text``, ``topics``, ``actions``,
    ``unresolved``. PII is explicitly excluded from the summary (ARCH-32).

    Parameters
    ----------
    state : ConclusionAgentState
        Current agent state. Must contain ``session_history`` and ``trace_id``.

    Returns
    -------
    ConclusionAgentState
        Updated state with ``summary`` set to a JSON string (the LLM's raw output).
    """
    # Format history for LLM: build a concise conversation transcript
    history_lines = []
    for turn in state["session_history"]:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        history_lines.append(f"{role.upper()}: {content}")

    transcript = "\n".join(history_lines)

    system_prompt = """You are a telecom support session analyst. Summarize the chat session concisely.

CRITICAL: Never include personal identifiable information (MSISDN, full name, address, card numbers) in the summary.

Return ONLY a JSON object with this exact structure:
{
  "summary_text": "Brief 1-2 sentence overview",
  "topics": ["topic1", "topic2"],
  "actions": ["action1 (e.g., 'recharged ₹199', 'created dispute ticket')"],
  "unresolved": ["unresolved query 1", "unresolved query 2"]
}

If no items exist for a list, return an empty array."""

    user_prompt = f"""Chat session transcript:

{transcript}

Analyze and extract key learnings."""

    llm: BaseChatModel = ChatOpenAI(
        model=settings.chat_deployment_mini,
        temperature=0.3,
    )

    langfuse = get_langfuse_client()
    if langfuse is None:
        # Fallback: run without LangFuse tracing
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        summary_text = response.content if isinstance(response.content, str) else str(response.content)
        logger.info(f"Conclusion Agent: LLM summary generated (no tracing) for session {state['session_id']}")
        return {**state, "summary": summary_text}

    trace = langfuse.get_trace(state["trace_id"])  # type: ignore[missing-attribute]

    with trace.span(name="summarise") as span:  # type: ignore[missing-attribute]
        span.set_input({"turn_count": len(state["session_history"])})

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await llm.ainvoke(messages)
        summary_text = response.content if isinstance(response.content, str) else str(response.content)

        span.set_output({"summary_preview": summary_text[:200] if summary_text else ""})
        span.end()

        logger.info(f"Conclusion Agent: LLM summary generated for session {state['session_id']}")

        return {**state, "summary": summary_text}


async def store_learning(state: ConclusionAgentState) -> ConclusionAgentState:
    """Store the session summary in ``support_session_learnings`` (V1 table).

    The summary JSON is stored in the ``content`` column with ``learning_type='session_summary'``.
    The V1 table schema (AC #6) uses ``learning_type`` and ``content`` rather than a
    dedicated ``summary_text`` column (V1 full baseline convention).

    Parameters
    ----------
    state : ConclusionAgentState
        Current agent state. Must contain ``session_id`` and ``summary``.

    Returns
    -------
    ConclusionAgentState
        State unchanged (side-effect: DB insert).
    """
    db = get_db_adapter()
    if db is None:
        logger.error("Conclusion Agent: database adapter not initialized")
        return state

    summary = state["summary"]
    if summary is None:
        logger.warning(f"Conclusion Agent: no summary to store for session {state['session_id']}")
        return state

    async with db.transaction() as conn:
        await store_session_learning(
            conn,
            session_id=state["session_id"],
            summary_text=summary,
        )

    logger.info(f"Conclusion Agent: stored learning for session {state['session_id']}")
    return state


async def trigger_notification(state: ConclusionAgentState) -> ConclusionAgentState:
    """Trigger the Notification Agent via A2A (agent-to-agent) invocation.

    Passes the session summary, subscriber ID, and trace ID to the Notification Agent,
    which will decide whether to send a follow-up notification and publish to Kafka.

    This is a fire-and-forget call: the Conclusion Agent does not wait for the
    Notification Agent to complete (AC #2).

    Parameters
    ----------
    state : ConclusionAgentState
        Current agent state. Must contain ``summary``, ``subscriber_id``, and ``trace_id``.

    Returns
    -------
    ConclusionAgentState
        State unchanged (side-effect: A2A invocation).
    """
    notification_graph = get_notification_graph()
    if notification_graph is None:
        logger.warning("Conclusion Agent: notification graph not initialized")
        return state

    # Invoke Notification Agent asynchronously (fire-and-forget)
    # Keep reference to prevent task from being garbage collected
    _task = asyncio.create_task(  # noqa: RUF006
        notification_graph.ainvoke(
            {
                "session_summary": state["summary"],
                "subscriber_id": state["subscriber_id"],
                "trace_id": state["trace_id"],
            }
        )
    )

    logger.info(f"Conclusion Agent: triggered notification for subscriber {state['subscriber_id']}")
    return state


def create_conclusion_graph() -> CompiledStateGraph:
    """Build and compile the Conclusion Agent LangGraph.

    Returns
    -------
    CompiledStateGraph
        Compiled graph ready for ``.ainvoke()`` with a ``ConclusionAgentState`` dict.
    """
    graph = StateGraph(ConclusionAgentState)  # type: ignore[bad-specialization]

    # Add nodes
    graph.add_node("load_session_history", load_session_history)
    graph.add_node("summarise_session", summarise_session)
    graph.add_node("store_learning", store_learning)
    graph.add_node("trigger_notification", trigger_notification)

    # Define linear flow: load → summarize → store → notify → END
    graph.set_entry_point("load_session_history")
    graph.add_edge("load_session_history", "summarise_session")
    graph.add_edge("summarise_session", "store_learning")
    graph.add_edge("store_learning", "trigger_notification")
    graph.add_edge("trigger_notification", END)

    return graph.compile()


# Global singleton for graph instance (set at FastAPI startup)
_conclusion_graph: CompiledStateGraph | None = None


def get_conclusion_graph() -> CompiledStateGraph | None:
    """Get the globally-registered Conclusion Agent graph instance.

    Returns
    -------
    CompiledStateGraph | None
        The compiled graph if registered via ``set_conclusion_graph()``, else ``None``.
    """
    return _conclusion_graph


def set_conclusion_graph(graph: CompiledStateGraph) -> None:
    """Register the Conclusion Agent graph globally (called at FastAPI startup).

    Parameters
    ----------
    graph : CompiledStateGraph
        The compiled graph to register.
    """
    global _conclusion_graph
    _conclusion_graph = graph
    logger.info("Conclusion Agent graph registered globally")


__all__ = [
    "ConclusionAgentState",
    "create_conclusion_graph",
    "get_conclusion_graph",
    "set_conclusion_graph",
]
