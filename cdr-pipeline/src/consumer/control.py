"""Worker controller — shared pause/resume signal for the CDR consumer pool (Story 2.5, AC #3/#4).

A single ``asyncio.Event`` (set = running) shared between the ``BatchProcessor``
and the management API. The batch loop calls ``await controller.running.wait()``
before each ``getmany`` poll; clearing the event parks the loop there within one
poll cycle (sub-second), satisfying the ≤2s stop guarantee (AC #3).

Single-process topology: consumer tasks + management API share the same event
loop, so the in-process ``asyncio.Event`` is the cleanest solution. If the
deployment ever splits them into separate processes, a Valkey control flag
(``control:cdr_workers``) checked per batch would be the fallback — document
that here and note which implementation is active.
"""

from __future__ import annotations

import asyncio


class WorkerController:
    """Pause/resume signal shared between the consumer pool and the management API."""

    def __init__(self) -> None:
        self._running: asyncio.Event = asyncio.Event()
        self._running.set()  # start in running state

    @property
    def running(self) -> asyncio.Event:
        """The event — set means running, cleared means paused."""
        return self._running

    def pause(self) -> None:
        """Clear the running event; the batch loop parks before its next poll."""
        self._running.clear()

    def resume(self) -> None:
        """Set the running event; the batch loop resumes polling."""
        self._running.set()

    @property
    def is_running(self) -> bool:
        """True when polling is active (event is set)."""
        return self._running.is_set()


__all__ = ["WorkerController"]
