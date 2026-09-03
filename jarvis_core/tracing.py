from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any


class PerformanceTrace:
    """Bounded monotonic command timeline suitable for hot paths."""

    def __init__(self, command_id=None, clock=time.perf_counter_ns):
        self.command_id = command_id or uuid.uuid4().hex[:12]
        self._clock, self._started, self._lock = clock, clock(), threading.RLock()
        self._marks = []

    def mark(self, stage, **metadata):
        with self._lock:
            elapsed = (self._clock() - self._started) / 1_000_000
            self._marks.append({"stage": str(stage), "elapsed_ms": round(elapsed, 3), "metadata": dict(metadata)})
            return elapsed

    def snapshot(self):
        with self._lock:
            return {
                "command_id": self.command_id,
                "duration_ms": self._marks[-1]["elapsed_ms"] if self._marks else 0,
                "timeline": [dict(row) for row in self._marks],
            }


class TraceStore:
    def __init__(self, limit=200):
        self._items: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
        self._lock = threading.RLock()

    def add(self, trace):
        with self._lock:
            self._items.append(trace.snapshot())

    def snapshot(self):
        with self._lock:
            return list(self._items)


TRACES = TraceStore()
