"""Per-request subscriber identity for the Support Agent (Story 5.4; ARCH-32).

The Support Agent tools (``get_balance`` / ``get_plan`` / ``get_usage``) must scope
every query to the *authenticated* subscriber, but LangGraph ``@tool`` callables
have no closure to receive request-scoped DI. Identity is therefore carried in
process-wide :mod:`contextvars` that are populated once per CopilotKit request by
the ``SupportIdentityMiddleware`` (it validates the Bearer JWT, resolves the
subscriber UUID from its ``sub`` claim and the MSISDN from the DB, and reads the
chat ``session_id`` from a request header).

Using ``contextvars`` (not module globals) means concurrent requests in the same
event loop are isolated — each async task sees only the identity set for it.

* ``subscriber_id`` — JWT ``sub`` (UUID string). Drives ``get_plan`` / ``get_usage``.
* ``msisdn`` — the *unmasked* MSISDN, looked up server-side from the subscriber.
  Never sent to the browser; never logged in full (ARCH-32). Drives
  ``get_balance`` (Valkey ``balance:{msisdn}``).
* ``session_id`` — the chat conversation id (from the ``X-Chat-Session-Id``
  header), keys the Valkey conversation context (AC #3).

If a tool runs outside a populated context (e.g. a unit test that injects state
directly, or a misconfigured deployment) the accessors raise ``RuntimeError`` so
the failure is loud rather than silently querying the wrong subscriber.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_subscriber_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("support_subscriber_id", default=None)
_msisdn: contextvars.ContextVar[str | None] = contextvars.ContextVar("support_msisdn", default=None)
_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("support_session_id", default="")

__all__ = [
    "current_msisdn",
    "current_session_id",
    "current_subscriber_id",
    "support_context",
]


@contextlib.contextmanager
def support_context(
    *,
    subscriber_id: str | None,
    msisdn: str | None,
    session_id: str,
) -> Iterator[None]:
    """Bind subscriber identity + session id for the duration of a request.

    Resets all three contextvars on exit so a worker task is never left with a
    prior request's identity. Use as ``with support_context(...): await ...`` from
    the request middleware.
    """
    sub_token = _subscriber_id.set(subscriber_id)
    msisdn_token = _msisdn.set(msisdn)
    session_token = _session_id.set(session_id)
    try:
        yield
    finally:
        _subscriber_id.reset(sub_token)
        _msisdn.reset(msisdn_token)
        _session_id.reset(session_token)


def current_subscriber_id() -> str:
    """Return the authenticated subscriber UUID (JWT ``sub``).

    Raises ``RuntimeError`` when no request context is bound — the graph is only
    reachable behind the identity middleware, so a missing context is a wiring bug.
    """
    value = _subscriber_id.get()
    if not value:
        raise RuntimeError("subscriber_id not bound — SupportIdentityMiddleware must wrap the request")
    return value


def current_msisdn() -> str:
    """Return the authenticated subscriber's unmasked MSISDN.

    Raises ``RuntimeError`` when no request context is bound. The MSISDN is the
    caller's identity claim resolved server-side; callers MUST NOT log it in full
    (ARCH-32 — use :func:`core.security.mask_msisdn` for any trace/log surface).
    """
    value = _msisdn.get()
    if not value:
        raise RuntimeError("msisdn not bound — SupportIdentityMiddleware must wrap the request")
    return value


def current_session_id() -> str:
    """Return the chat session id for this request (may be empty in tests)."""
    return _session_id.get()
