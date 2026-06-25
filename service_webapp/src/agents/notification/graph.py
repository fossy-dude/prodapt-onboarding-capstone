"""Notification Agent LangGraph for session-end follow-up notification decisions (Story 5.10 AC #3, #4, #5).

A conditional A2A agent invoked by the Conclusion Agent to decide whether a follow-up
notification is warranted after a chat session ends. The LLM evaluates the session
summary and decides: should we notify? If so, what type, channel, and delay?

    ┌──────────────────────┐
    │ decide_notification  │  (LLM call: gpt-4o-mini)
    └──────────────────────┘
            │
            ▼
        should_send?
       /             \
      YES             NO
      │                │
      ▼                ▼
┌─────────────────┐   │
│ publish_notification│  │
└─────────────────┘   │
      │                │
      └────┬───────────┘
           ▼
          END

* Only executes ``publish_notification`` if ``should_send=True`` (conditional edge).
* Notification types: ``RECHARGE_REMINDER``, ``PLAN_SUGGESTION``, ``DISPUTE_FOLLOWUP``, ``NONE``.
* Channels: ``push`` or ``sms``.
* Delays: ``0`` (now), ``1`` (+1 hour), ``24`` (+24 hours).
* Publishes to ``notification.events`` Kafka topic with ``subscriber_id`` as key (ARCH-11).
* Each node execution is traced to LangFuse as a child span under the Conclusion Agent trace.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from core.config import settings
from core.observability.langfuse import get_langfuse_client
from models.envelope import EventEnvelope

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# Notification type constants (AC #3)
NotificationType = Literal["RECHARGE_REMINDER", "PLAN_SUGGESTION", "DISPUTE_FOLLOWUP", "NONE"]
NotificationChannel = Literal["push", "sms"]


class NotificationAgentState(TypedDict):
    """State for the Notification Agent.

    Attributes
    ----------
    session_summary : str
        JSON-structured session summary from the Conclusion Agent. Contains
        ``summary_text``, ``topics``, ``actions``, ``unresolved``.
    subscriber_id : str
        The subscriber UUID for targeting and Kafka key partitioning.
    should_send : bool | None
        ``True`` if the LLM decides a notification is warranted, ``False`` otherwise.
        Set after ``decide_notification`` node.
    notification_type : str | None
        One of ``RECHARGE_REMINDER``, ``PLAN_SUGGESTION``, ``DISPUTE_FOLLOWUP``, ``NONE``.
        Set after ``decide_notification`` node.
    channel : str | None
        Delivery channel: ``push`` or ``sms``. Set after ``decide_notification`` node.
    delay_hours : int | None
        Delay before sending: ``0`` (now), ``1`` (+1h), ``24`` (+24h). Set after
        ``decide_notification`` node.
    trace_id : str
        LangFuse trace id for nested span tracing (FR-72). Propagated from the
        Conclusion Agent.
    """

    session_summary: str
    subscriber_id: str
    should_send: bool | None
    notification_type: str | None
    channel: str | None
    delay_hours: int | None
    trace_id: str


async def decide_notification(state: NotificationAgentState) -> NotificationAgentState:
    """Use the LLM to decide whether a follow-up notification is warranted.

    The LLM evaluates the session summary and decides:
    1. Should we send a notification? (yes/no)
    2. What type? (RECHARGE_REMINDER/PLAN_SUGGESTION/DISPUTE_FOLLOWUP/NONE)
    3. Which channel? (push/sms)
    4. When? (0=now, 1=+1h, 24=+24h)

    The response must be JSON with keys: ``should_send``, ``type``, ``channel``,
    ``delay_hours``. PII is explicitly excluded from the decision (ARCH-32).

    Parameters
    ----------
    state : NotificationAgentState
        Current agent state. Must contain ``session_summary`` and ``trace_id``.

    Returns
    -------
    NotificationAgentState
        Updated state with ``should_send``, ``notification_type``, ``channel``,
        and ``delay_hours`` set from the LLM response.
    """
    system_prompt = """You are a telecom notification decision agent. Based on this chat session summary, decide if a follow-up notification is warranted.

Return ONLY a JSON object with this exact structure:
{
  "should_send": true/false,
  "type": "RECHARGE_REMINDER|PLAN_SUGGESTION|DISPUTE_FOLLOWUP|NONE",
  "channel": "push|sms",
  "delay_hours": 0|1|24
}

Guidelines:
- RECHARGE_REMINDER: if subscriber discussed low balance but didn't recharge
- PLAN_SUGGESTION: if subscriber asked about plans but didn't upgrade
- DISPUTE_FOLLOWUP: if subscriber opened a ticket (channel=sms, delay_hours=1)
- NONE: if no follow-up needed (should_send=false)
- Default to channel=push, delay_hours=0 unless specific reason otherwise"""

    user_prompt = f"""Chat session summary:

{state["session_summary"]}

Decide: should we send a follow-up notification?"""

    llm: BaseChatModel = ChatOpenAI(
        model=settings.chat_deployment_mini,
        temperature=0.3,
    )

    langfuse = get_langfuse_client()
    trace = langfuse.get_trace(state["trace_id"])

    with trace.span(name="decide_notification") as span:
        span.set_input({"session_summary": state["session_summary"][:200]})

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await llm.ainvoke(messages)
        decision_text = response.content

        # Parse JSON response
        try:
            decision = json.loads(decision_text)
            should_send = bool(decision.get("should_send", False))
            notification_type = str(decision.get("type", "NONE"))
            channel = str(decision.get("channel", "push"))
            delay_hours = int(decision.get("delay_hours", 0))

            # Validate types
            if notification_type not in ("RECHARGE_REMINDER", "PLAN_SUGGESTION", "DISPUTE_FOLLOWUP", "NONE"):
                notification_type = "NONE"
            if channel not in ("push", "sms"):
                channel = "push"
            if delay_hours not in (0, 1, 24):
                delay_hours = 0

            span.set_output(
                {
                    "should_send": should_send,
                    "type": notification_type,
                    "channel": channel,
                    "delay_hours": delay_hours,
                }
            )
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Notification Agent: failed to parse LLM response: {e}")
            should_send = False
            notification_type = "NONE"
            channel = "push"
            delay_hours = 0
            span.set_output({"error": "Failed to parse decision", "should_send": False})
        finally:
            span.end()

        logger.info(
            f"Notification Agent: decision for subscriber {state['subscriber_id']}: "
            f"should_send={should_send}, type={notification_type}"
        )

        return {
            **state,
            "should_send": should_send,
            "notification_type": notification_type,
            "channel": channel,
            "delay_hours": delay_hours,
        }


async def publish_notification(state: NotificationAgentState) -> NotificationAgentState:
    """Publish the notification event to the ``notification.events`` Kafka topic.

    Only executes if ``should_send=True`` (conditional routing). The event envelope
    contains the notification decision payload, keyed by ``subscriber_id`` for
    partitioning (ARCH-11). The session summary is truncated to 200 chars for PII safety.

    Parameters
    ----------
    state : NotificationAgentState
        Current agent state. Must contain ``should_send=True``, ``notification_type``,
        ``channel``, ``delay_hours``, ``subscriber_id``, and ``trace_id``.

    Returns
    -------
    NotificationAgentState
        State unchanged (side-effect: Kafka publish).
    """
    # This should never execute if should_send is False (due to conditional edge)
    # but we guard defensively
    if not state.get("should_send"):
        logger.warning("Notification Agent: publish_notification called with should_send=False")
        return state

    # Get kafka producer singleton from app state
    producer = getattr(_kafka_producer, "producer", None)
    if producer is None:
        logger.error("Notification Agent: kafka producer not initialized")
        return state

    # Build notification event payload
    payload = {
        "type": state["notification_type"],
        "subscriber_id": state["subscriber_id"],
        "channel": state["channel"],
        "delay_hours": state["delay_hours"],
        "session_summary": state["session_summary"][:200],  # Truncate for PII safety (AC #3)
    }

    # Create event envelope
    envelope = EventEnvelope.new(
        event_type="notification.session_end",
        payload=payload,
        trace_id=state["trace_id"],
    )
    envelope_bytes = envelope.model_dump_json().encode()

    # Traceparent header for distributed tracing (W3C standard)
    traceparent = f"00-{state['trace_id']}-{'0' * 16}-01"
    headers = [("traceparent", traceparent.encode())]

    # Publish to Kafka topic
    await producer.send(
        "notification.events",
        value=envelope_bytes,
        key=str(state["subscriber_id"]).encode(),
        headers=headers,
    )

    logger.info(
        f"Notification Agent: published notification event for subscriber {state['subscriber_id']}: "
        f"type={state['notification_type']}, channel={state['channel']}, delay={state['delay_hours']}h"
    )

    return state


def should_route_to_publish(state: NotificationAgentState) -> Literal["publish", "end"]:
    """Conditional routing function for the Notification Agent.

    Routes to ``publish_notification`` if ``should_send=True``, otherwise to END.

    Parameters
    ----------
    state : NotificationAgentState
        Current agent state. Must contain ``should_send``.

    Returns
    -------
    Literal["publish", "end"]
        ``"publish"`` if should_send is True, ``"end"`` otherwise.
    """
    return "publish" if state.get("should_send") else "end"


def create_notification_graph() -> CompiledStateGraph:
    """Build and compile the Notification Agent LangGraph.

    Returns
    -------
    CompiledStateGraph
        Compiled graph ready for ``.ainvoke()`` with a ``NotificationAgentState`` dict.
    """
    graph = StateGraph(NotificationAgentState)

    # Add nodes
    graph.add_node("decide_notification", decide_notification)
    graph.add_node("publish_notification", publish_notification)

    # Define conditional flow: decide → (should_send? → publish : END)
    graph.set_entry_point("decide_notification")
    graph.add_conditional_edges(
        "decide_notification",
        should_route_to_publish,
        {
            "publish": "publish_notification",
            "end": END,
        },
    )
    graph.add_edge("publish_notification", END)

    return graph.compile()


# Global singleton for graph instance (set at FastAPI startup)
_notification_graph: CompiledStateGraph | None = None

# Global singleton for kafka producer (set at FastAPI startup)
_kafka_producer: object | None = None


def get_notification_graph() -> CompiledStateGraph | None:
    """Get the globally-registered Notification Agent graph instance.

    Returns
    -------
    CompiledStateGraph | None
        The compiled graph if registered via ``set_notification_graph()``, else ``None``.
    """
    return _notification_graph


def set_notification_graph(graph: CompiledStateGraph) -> None:
    """Register the Notification Agent graph globally (called at FastAPI startup).

    Parameters
    ----------
    graph : CompiledStateGraph
        The compiled graph to register.
    """
    global _notification_graph
    _notification_graph = graph
    logger.info("Notification Agent graph registered globally")


def set_kafka_producer(producer: object) -> None:
    """Register the Kafka producer globally for the Notification Agent.

    Parameters
    ----------
    producer : object
        The AIOKafkaProducer instance (set at FastAPI startup).
    """
    global _kafka_producer
    _kafka_producer = type("obj", (object,), {"producer": producer})()
    logger.info("Notification Agent kafka producer registered globally")


__all__ = [
    "NotificationAgentState",
    "create_notification_graph",
    "get_notification_graph",
    "set_kafka_producer",
    "set_notification_graph",
]
