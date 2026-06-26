"""Observability primitives for agent / LLM tracing.

Story 1.5 ships the LangFuse client singleton and ``@trace_agent`` decorator
(see :mod:`core.observability.langfuse`). Infra-level spans stay on the OTEL
pipeline (:mod:`core.middleware`) — LangFuse records agent/LLM traces only
(architecture §1.10.2).
"""
