"""LangFuse client singleton and ``@trace_agent`` decorator (Story 1.5; FR-72).

This module is the reusable observability primitive every future agentic
workflow decorates itself with, so agent tracing exists from the first agent
story (Epic 5) with no per-agent setup. It owns two things:

* :func:`get_langfuse_client` — a process-wide :class:`langfuse.Langfuse`
  singleton built from ``settings`` (host / public key / secret key).
* :func:`trace_agent` — an ``async`` decorator that records one LangFuse
  generation per wrapped call: trace **name**, **input**, **output**,
  **model** and **token usage** (FR-72), with the OTEL ``trace_id`` carried in
  metadata so the OTEL trace (Story 1.4) and the LangFuse trace correlate
  (architecture §1.13.7).

The critical contract — AC #4 / architecture §1.10.2 — is the **no-op gate**:
when ``LANGFUSE_ENABLED=false`` the decorator is a *pure pass-through* and
``get_langfuse_client`` returns ``None`` *without ever constructing* a
:class:`langfuse.Langfuse`. That is what lets the entire test suite and CI
(which have no LangFuse server) run with zero LangFuse overhead.

SDK version note: ``langfuse>=2`` currently resolves to **v4.x**, which is
OTEL-based. The v2 ``client.trace()`` / ``trace.generation()`` surface was
removed, so we use the v4 ``client.start_as_current_observation(...)``
context manager plus ``observation.update(...)`` (the current decorator /
context-manager API the dev note directs us to use).

PII hygiene contract (architecture §1.11.6 / NFR-16): ``@trace_agent`` records
its ``args`` / ``kwargs`` **verbatim** and does not scrub them — it guarantees
only that it will not *add* leakage. Callers MUST NOT pass raw MSISDN, names,
addresses or card data as arguments; sanitise upstream (subscriber UUID or
``msisdn[-4:]``). This keeps the decorator generic instead of guessing which
fields are sensitive per call site.
"""

from __future__ import annotations

import atexit
import contextvars
import functools
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any
from langfuse.langchain import CallbackHandler

from langfuse import Langfuse

from core.config import settings

__all__ = [
    "current_trace_id",
    "get_langfuse_client",
    "set_trace_id",
    "set_trace_usage",
    "trace_agent",
]

_logger = logging.getLogger(__name__)

# A generic async callable. ParamSpec is avoided: this pyrefly version rejects
# ``P.args``/``P.kwargs`` annotations and the codebase doesn't use it elsewhere.
AsyncFunc = Callable[..., Awaitable[Any]]

# ── Singleton cache ───────────────────────────────────────────────────────────
# ``None`` is a *valid* disabled return, so a separate "initialised" flag
# distinguishes "not computed yet" from "computed and disabled". This keeps the
# disabled path from ever reaching the ``Langfuse(...)`` constructor.
_langfuse_client: Langfuse | None = None
_langfuse_client_initialised: bool = False

# ── Request/call-scoped contextvars ───────────────────────────────────────────
# trace_id: bound per request from OtelTraceMiddleware (Story 1.4) so the
#   LangFuse trace shares the OTEL trace id (architecture §1.13.7).
# usage: bound per in-flight @trace_agent call from the LLM response so the
#   decorator can record token usage (FR-72) without the agent returning it.
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("langfuse_trace_id", default=None)
_usage_var: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar("langfuse_usage", default=None)


def get_langfuse_callback_handler():
    return CallbackHandler()


def get_langfuse_client() -> Langfuse | None:
    """Return the cached LangFuse client singleton, or ``None`` when disabled.

    When ``settings.langfuse_enabled`` is False the client is **never**
    constructed — the function sets the cache to ``None`` and returns before
    the :class:`langfuse.Langfuse` constructor runs, so disabled operation is
    connection-free. Callers (and :func:`trace_agent`) short-circuit on the
    ``None`` return (AC #4).

    If the constructor raises (bad host, invalid keys), the error is logged,
    ``None`` is returned, and the singleton is cached as disabled — graceful
    degradation rather than crashing every agent call.
    """
    global _langfuse_client, _langfuse_client_initialised
    if _langfuse_client_initialised:
        return _langfuse_client
    _langfuse_client_initialised = True
    if not settings.langfuse_enabled:
        _langfuse_client = None
        return None
    # Built from settings only — no hard-coded host/keys (architecture §1.11.1).
    try:
        _langfuse_client = Langfuse(
            host=settings.langfuse_base_url,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        atexit.register(_langfuse_client.flush)
    except Exception as exc:
        _logger.warning("LangFuse client init failed, observability disabled: %s", exc)
        _langfuse_client = None
    return _langfuse_client


def _reset_langfuse_client_for_tests() -> None:
    """Clear the cached singleton.

    Test-only: tests toggle ``settings.langfuse_enabled`` and must drop the
    cache between cases so the new flag takes effect.
    """
    global _langfuse_client, _langfuse_client_initialised
    _langfuse_client = None
    _langfuse_client_initialised = False


def set_trace_id(trace_id: str | None) -> contextvars.Token[str | None]:
    """Bind the OTEL ``trace_id`` for the current async context (request lifespan)."""
    return _trace_id_var.set(trace_id)


def current_trace_id() -> str | None:
    """Return the ``trace_id`` active for the current async context, if any."""
    return _trace_id_var.get()


def set_trace_usage(usage: dict[str, int] | None) -> contextvars.Token[dict[str, int] | None]:
    """Bind token usage for the in-flight ``@trace_agent`` call (e.g. from the LLM response)."""
    return _usage_var.set(usage)


def _capture_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build the trace input payload from the call's positional/keyword args.

    Falls back to repr() strings if the payload is not JSON-serializable, so
    non-serializable objects (Pydantic models, dataclasses, etc.) never crash
    the SDK at the network boundary. See module PII hygiene contract for why
    no scrubbing occurs here.
    """
    payload: dict[str, Any] = {"args": list(args), "kwargs": dict(kwargs)}
    try:
        json.dumps(payload)
    except (TypeError, ValueError):
        payload = {"args": repr(args), "kwargs": repr(kwargs)}
    return payload


def trace_agent(
    name: str | AsyncFunc | None = None,
    *,
    model: str | None = None,
) -> AsyncFunc | Callable[[AsyncFunc], AsyncFunc]:
    """Record a LangFuse trace around an ``async`` function (FR-72).

    Captures trace **name** (default = the wrapped function's ``__name__``,
    overridable), **input** args/kwargs, **output**/return value, **model**, and
    **token usage** (when :func:`set_trace_usage` was bound *during* the wrapped
    call — read after ``await fn(...)`` so LLM-response usage is captured).
    The OTEL ``trace_id`` (when :func:`set_trace_id` was bound) is carried in the
    observation metadata so OTEL and LangFuse traces correlate (§1.13.7).

    When ``LANGFUSE_ENABLED=false`` the wrapper is a **pure pass-through**: it
    calls the wrapped function directly with zero LangFuse overhead and no
    client construction (AC #4) — identical signature, return value and
    exceptions to the undecorated function.

    If LangFuse is enabled but the observation fails to open (network error,
    SDK bug), the decorator falls back to a transparent pass-through so the
    business call is never sacrificed for observability. Similarly, SDK errors
    on ``observation.update()`` are suppressed (logged) after the business call
    returns successfully.

    Usable in any of these forms::

        @trace_agent                              # bare
        async def run(...): ...

        @trace_agent()                            # defaults
        async def run(...): ...

        @trace_agent("recharge_agent", model="gpt-4o")
        async def run(...): ...

    PII hygiene (§1.11.6): do NOT pass raw MSISDN/name/card as args — the
    decorator records them verbatim and does not scrub them.
    """
    # Bare ``@trace_agent`` (no call) passes the wrapped function as the first
    # positional arg, i.e. ``name`` is callable. Resolve which it is up front so
    # the closure below holds a plain ``str | None`` trace name.
    bare_func: AsyncFunc | None = name if callable(name) else None
    explicit_name: str | None = None if callable(name) else name

    def decorator(fn: AsyncFunc) -> AsyncFunc:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            client = get_langfuse_client()
            # No-op gate: disabled → transparent pass-through, no LangFuse work.
            if client is None:
                return await fn(*args, **kwargs)

            trace_name = explicit_name or fn.__name__
            trace_id = current_trace_id()
            metadata = {"trace_id": trace_id} if trace_id else {}

            # Guard __enter__: if LangFuse fails to open the observation (bad
            # host, SDK error), fall back to untraced execution — observability
            # must never kill a business call.
            try:
                observation_cm = client.start_as_current_observation(
                    name=trace_name,
                    as_type="generation",
                    input=_capture_input(args, kwargs),
                    model=model,
                    metadata=metadata,
                )
                observation = observation_cm.__enter__()
            except Exception as exc:
                _logger.warning("LangFuse observation open failed, running untraced: %s", exc)
                return await fn(*args, **kwargs)

            try:
                try:
                    output = await fn(*args, **kwargs)
                except BaseException:
                    # Catches both Exception and CancelledError / KeyboardInterrupt.
                    # Flag the observation, suppress any secondary SDK error, then
                    # re-raise the original so the caller sees the real failure.
                    try:
                        observation.update(level="ERROR")
                    except Exception:
                        pass
                    raise
                # Read usage AFTER fn() completes — agents call set_trace_usage()
                # from inside the LLM response handler (FR-72).
                usage = _usage_var.get()
                update_kwargs: dict[str, Any] = {"output": output}
                if usage is not None:
                    update_kwargs["usage_details"] = usage
                try:
                    observation.update(**update_kwargs)
                except Exception as exc:
                    _logger.warning("LangFuse observation update failed: %s", exc)
                return output
            finally:
                # Always close the context manager, even on cancellation.
                # Pass the active exception info so the CM can record failures.
                try:
                    observation_cm.__exit__(*sys.exc_info())
                except Exception:
                    pass

        return wrapper

    if bare_func is not None:
        return decorator(bare_func)
    return decorator
