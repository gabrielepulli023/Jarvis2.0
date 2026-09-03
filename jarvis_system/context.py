from __future__ import annotations
import threading
import time
from collections import deque
from typing import Any
from jarvis_core.operational_context import OperationalContext


class ContextEngine:
    """Event-fed, bounded, read-only view of the user's current operating context."""

    def __init__(self, events, state, processes, memory, missions, windows=None, history_limit: int = 64):
        self.events = events
        self.state = state
        self.processes = processes
        self.memory = memory
        self.missions = missions
        self.windows = windows
        self._lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=max(16, int(history_limit)))
        # Short-lived hand-off for real tool results.  It is intentionally
        # volatile: conversational memory and operational artifacts have
        # different retention and safety rules.
        self.operational = OperationalContext()
        self._unsubscribers = [events.subscribe("*", self._remember)]

    def _remember(self, event):
        with self._lock:
            self._events.append(
                {
                    "topic": event.topic,
                    "source": event.source,
                    "timestamp": event.timestamp,
                    "payload": self._safe_payload(event.payload),
                }
            )

    @staticmethod
    def _safe_payload(payload):
        blocked = ("password", "secret", "token", "api_key", "authorization")
        return {
            str(key): ("[REDACTED]" if any(word in str(key).casefold() for word in blocked) else str(value)[:500])
            for key, value in dict(payload or {}).items()
        }

    def snapshot(self) -> dict:
        active = None
        if self.windows is not None:
            try:
                row = self.windows.active()
                active = (
                    None
                    if row is None
                    else {"title": row.title, "pid": row.pid, "executable": row.executable, "monitor": row.monitor}
                )
            except OSError:
                active = None
        managed = self.processes.snapshot()
        opened = [row for row in managed if row["running"]]
        with self._lock:
            events = list(self._events)[-20:]
        return {
            "captured_at": time.time(),
            "active_window": active,
            "opened_apps": opened,
            "current_task": self.missions.recent(1),
            "conversation": self.memory.working.snapshot(),
            "system_state": self.state.snapshot(),
            "recent_events": events,
        }

    def record_operational_result(self, tool: str, result: dict | None, arguments: dict | None = None) -> dict:
        return self.operational.record(tool, result, arguments)

    def operational_context(self) -> dict | None:
        return self.operational.current()

    def close(self):
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
