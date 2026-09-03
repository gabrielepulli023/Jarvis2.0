from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .events import EventBus
from .logging import redact


@dataclass(frozen=True, slots=True)
class EmergencyStopResult:
    sequence: int
    timestamp: float
    callbacks: int
    failures: tuple[str, ...]


class EmergencyStopCoordinator:
    """Priority cancellation fan-out. Callbacks must be bounded and idempotent."""

    def __init__(self, events: EventBus):
        self.events = events
        self._callbacks: list[tuple[str, Callable[[], object]]] = []
        self._lock = threading.RLock()
        self._active = threading.Event()
        self._sequence = 0

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def register(self, name: str, callback: Callable[[], object]) -> Callable[[], None]:
        entry = (str(name), callback)
        with self._lock:
            self._callbacks.append(entry)

        def remove():
            with self._lock:
                if entry in self._callbacks:
                    self._callbacks.remove(entry)

        return remove

    def trigger(self, source: str = "user") -> EmergencyStopResult:
        with self._lock:
            self._active.set()
            self._sequence += 1
            sequence = self._sequence
            callbacks = tuple(self._callbacks)
        self.events.publish("emergency.stop", {"sequence": sequence}, source=source, priority=1000)
        failures = []
        for name, callback in callbacks:
            started = time.monotonic()
            try:
                callback()
            except Exception as exc:
                failures.append(redact(f"{name}: {type(exc).__name__}: {exc}"))
            if time.monotonic() - started > 2.0:
                failures.append(f"{name}: timeout budget exceeded")
        result = EmergencyStopResult(sequence, time.time(), len(callbacks), tuple(failures))
        self.events.publish(
            "emergency.stopped", {"sequence": sequence, "failures": list(failures)}, source="emergency", priority=1000
        )
        return result

    def reset(self) -> None:
        self._active.clear()
        self.events.publish("emergency.reset", source="user", priority=1000)
