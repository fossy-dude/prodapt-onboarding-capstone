"""CopilotKit runtime FastAPI router (Story 5.4 AC #1, #6; architecture §1.6.1).

Wires the compiled Support Agent LangGraph graph onto a CopilotKit remote
endpoint so the frontend ``<CopilotKit runtimeUrl="/api/chat">`` can stream AG-UI
events (``TextMessageContent`` etc.) over SSE. CopilotKit owns the AG-UI event
marshalling — we do NOT hand-roll SSE here (architecture §1.6.1).

Installed-SDK surface (the story's ``LangGraphAgent`` / ``CopilotKitSDK`` names
were renamed in the installed ``copilotkit``):

* ``CopilotKitRemoteEndpoint(agents=[...])`` — the endpoint (``CopilotKitSDK`` is
  deprecated).
* ``LangGraphAGUIAgent(*, name, graph, description)`` — the AG-UI LangGraph agent.
* ``add_fastapi_endpoint(app, sdk, prefix)`` — registers a catch-all route at
  ``{prefix}/{path:path}`` covering the AG-UI protocol paths (``/info``,
  ``/message``, ``/stream`` …). We use prefix ``/api/chat`` so the runtime lives
  under ``/api/chat/*`` including ``POST /api/chat/stream`` (AC #1).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import CopilotKitRemoteEndpoint, LangGraphAGUIAgent
from copilotkit.integrations.fastapi import add_fastapi_endpoint
from copilotkit.sdk import CopilotKitContext
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from langchain_openai import AzureChatOpenAI

from agents.support.graph import build_support_graph
from agents.support.tools import set_support_adapters
from core.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.protocols.cache import CacheProtocol
    from core.protocols.db import DatabaseProtocol

logger = logging.getLogger(__name__)

__all__ = ["CHAT_ENDPOINT_PREFIX", "setup_copilotkit"]


# CopilotKit registers a catch-all at ``{prefix}/{path:path}``; ``/api/chat`` puts
# the runtime (incl. ``POST /api/chat/stream``) under /api/chat/* (AC #1, ARCH-13).
CHAT_ENDPOINT_PREFIX = "/api/chat"

_SUPPORT_AGENT_NAME = "support_agent"
_SUPPORT_AGENT_DESCRIPTION = "Billing and account assistant for MVNO subscribers."


def setup_copilotkit(
    app: FastAPI,
    *,
    cache: CacheProtocol | None = None,
    db: DatabaseProtocol | None = None,
    azure_endpoint: str | None = None,
    api_key: str | None = None,
    api_version: str | None = None,
    deployment: str | None = None,
) -> None:
    """Wire the CopilotKit runtime + Support Agent onto ``app``.

    Resolves the cache/DB from ``app.state`` when not injected (the lifespan sets
    ``cache_adapter`` / ``db_adapter``). The Azure OpenAI client is built from
    ``settings`` unless explicit values are supplied (tests pass fakes by building
    the graph elsewhere — this setup is a no-op when CopilotKit/Azure are not
    configured, so the app still boots for lint/test without secrets).

    Idempotent: safe to call once per app. Returns early without registering when
    the chat deployment cannot be configured, so a missing Azure key never blocks
    boot (the chatbot is simply unavailable).
    """
    resolved_cache = cache if cache is not None else getattr(app.state, "cache_adapter", None)
    resolved_db = db if db is not None else getattr(app.state, "db_adapter", None)
    set_support_adapters(resolved_cache, resolved_db)

    endpoint = azure_endpoint if azure_endpoint is not None else settings.azure_openai_endpoint
    key = api_key if api_key is not None else settings.azure_openai_api_key
    version = api_version if api_version is not None else settings.azure_openai_api_version
    deployment_name = deployment if deployment is not None else settings.chat_deployment_mini

    # Azure OpenAI is optional — degrade to "no chatbot" rather than crashing boot.
    if not endpoint or not key or not deployment_name:
        logger.warning(
            "CopilotKit runtime not registered: Azure OpenAI not configured "
            "(endpoint/key/deployment missing). Chatbot will be unavailable."
        )
        return

    llm = AzureChatOpenAI(
        azure_endpoint=endpoint,
        api_key=key,
        api_version=version,
        azure_deployment=deployment_name,
        temperature=0.2,
    )
    graph = build_support_graph(llm)
    add_langgraph_fastapi_endpoint(
        app=app,
        agent=LangGraphAGUIAgent(
            name=_SUPPORT_AGENT_NAME,
            description=_SUPPORT_AGENT_DESCRIPTION,
            graph=graph,
        ),
        path=CHAT_ENDPOINT_PREFIX,
    )

    # # Register the direct AG-UI run route BEFORE the copilotkit catch-all so the
    # # JS SDK's POST /api/chat/agent/{name}/run hits agent.run() rather than the
    # # copilotkit sdk.execute_agent() path that calls agent.execute() (which
    # # LangGraphAGUIAgent does not implement, causing AttributeError → 500).
    # _register_agui_run_routes(app, CHAT_ENDPOINT_PREFIX, agents)

    # # _V1CompatEndpoint handles the info probe: JS SDK v1.x expects agents as an
    # # object keyed by name, but copilotkit v0.x returns an array.
    # sdk = _V1CompatEndpoint(agents=agents)  # type: ignore[arg-type]
    # add_fastapi_endpoint(app, sdk, CHAT_ENDPOINT_PREFIX)
    logger.info("CopilotKit runtime registered at %s/* (agent=%s)", CHAT_ENDPOINT_PREFIX, _SUPPORT_AGENT_NAME)
