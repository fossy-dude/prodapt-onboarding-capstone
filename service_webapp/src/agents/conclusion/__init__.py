"""Conclusion Agent LangGraph for session-end summarization and notification triggering (Story 5.10).

This module exports the compiled Conclusion Agent graph for use in the support chat
endpoint and background TTL polling.
"""

from __future__ import annotations

from agents.conclusion.graph import (
    create_conclusion_graph,
    get_conclusion_graph,
    set_conclusion_graph,
)

__all__ = ["create_conclusion_graph", "get_conclusion_graph", "set_conclusion_graph"]
