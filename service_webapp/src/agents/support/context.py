"""Conversational context store in a Valkey HASH (Story 5.4 AC #3; ARCH-5).

The chatbot must remember the last turns of a conversation so it can answer
follow-ups ("and how much data is left?") without the subscriber re-stating
context. CopilotKit streams the *current* message turn; cross-turn persistence
lives here, in Valkey, keyed per session:

* key      — ``chat_context:{session_id}`` (HASH)
* field    — ``turn_{n}`` (zero-based, monotonic)
* value    — ``json.dumps({"role": ..., "content": ...})``
* TTL      — 7200s (2h), **re-set on every write** so the window slides from
  the last message (a session idle for 2h expires — ARCH-5).

Sliding window: at most :data:`MAX_CONTEXT_TURNS` (10) fields are kept. Each save
re-writes the HASH with the most recent 10 turns re-indexed ``turn_0`` …
``turn_9`` (the oldest is dropped when the window is full) — cheap because the
window is tiny, and it keeps field names bounded over a long session.

The functions take the cache adapter as a parameter (the same
:class:`CacheProtocol` resolved on ``app.state.cache_adapter``) so they are
trivially unit-testable with a fake that implements ``hgetall`` / ``hset`` /
``delete``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.protocols.cache import CacheProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "CHAT_CONTEXT_TTL_SECONDS",
    "MAX_CONTEXT_TURNS",
    "context_key",
    "load_context",
    "save_turn",
]

# 2h sliding TTL (epics.md:1582; ARCH-5). Re-set on every write.
CHAT_CONTEXT_TTL_SECONDS: int = 7200
# Last-N turns retained (epics.md:1582 — "last 10 turns").
MAX_CONTEXT_TURNS: int = 10

_TURN_PREFIX = "turn_"


def context_key(session_id: str) -> str:
    """Return the Valkey HASH key for a chat session's context."""
    return f"chat_context:{session_id}"


def _decode_turns(raw: dict[str, str]) -> list[tuple[int, dict]]:
    """Parse an ``hgetall`` result into sorted ``(index, message)`` pairs.

    Malformed fields (bad index, bad JSON, or a value that is not a message dict)
    are skipped rather than fatal — a corrupt single turn must not break the whole
    conversation (a non-dict value would later crash ``turn.get("role")``).
    """
    parsed: list[tuple[int, dict]] = []
    for field, value in raw.items():
        if not field.startswith(_TURN_PREFIX):
            continue
        idx_str = field[len(_TURN_PREFIX) :]
        if not idx_str.isdigit():
            continue
        try:
            msg = json.loads(value)
        except (TypeError, ValueError):
            logger.debug("load_context: skipping unparseable turn field=%s", field)
            continue
        if not isinstance(msg, dict):
            logger.debug("load_context: skipping non-dict turn field=%s", field)
            continue
        parsed.append((int(idx_str), msg))
    parsed.sort(key=lambda item: item[0])
    return parsed


async def load_context(cache: CacheProtocol, session_id: str) -> list[dict]:
    """Load the conversation history for ``session_id`` (oldest → newest).

    Returns at most :data:`MAX_CONTEXT_TURNS` message dicts
    (``{"role": str, "content": str}``). Empty list for a fresh session.
    """
    raw = await cache.hgetall(context_key(session_id))
    turns = _decode_turns(raw)
    messages = [msg for _, msg in turns]
    return messages[-MAX_CONTEXT_TURNS:]


async def save_turn(
    cache: CacheProtocol,
    session_id: str,
    role: str,
    content: str,
) -> None:
    """Append one turn to the session context, enforcing the sliding window + TTL.

    Re-writes the HASH with the most recent :data:`MAX_CONTEXT_TURNS` turns
    re-indexed from 0, then sets the 2h TTL — so the window slides from the last
    message and a long-idle session expires (ARCH-5).
    """
    existing = await load_context(cache, session_id)
    window = [*existing, {"role": role, "content": content}][-MAX_CONTEXT_TURNS:]

    mapping = {f"{_TURN_PREFIX}{idx}": json.dumps(msg) for idx, msg in enumerate(window)}

    # Clear the key first so stale higher-indexed fields from a prior (longer)
    # window cannot survive — HSET only adds/overwrites, it does not remove.
    await cache.delete(context_key(session_id))
    await cache.hset(context_key(session_id), mapping, ex=CHAT_CONTEXT_TTL_SECONDS)
