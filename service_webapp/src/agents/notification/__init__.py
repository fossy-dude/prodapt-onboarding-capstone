"""Notification Agent LangGraph for session-end follow-up notification decisions (Story 5.10).

This module exports the compiled Notification Agent graph for use in the Conclusion Agent.
"""

from __future__ import annotations

from agents.notification.graph import create_notification_graph

__all__ = ["create_notification_graph"]
