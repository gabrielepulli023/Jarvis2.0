from __future__ import annotations
import threading
from copy import deepcopy
from typing import Any
from .events import EventBus


class StateManager:
    def __init__(self, events: EventBus):
        self._events = events
        self._values: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._values.get(key, default))

    def set(self, key: str, value: Any, *, source: str = "core") -> None:
        with self._lock:
            previous = self._values.get(key)
            self._values[key] = deepcopy(value)
        if previous != value:
            self._events.publish("state.changed", {"key": key, "previous": previous, "value": value}, source=source)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._values)
