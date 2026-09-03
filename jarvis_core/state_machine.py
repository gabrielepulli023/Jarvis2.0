from __future__ import annotations

import threading
from enum import StrEnum

from .events import EventBus


class JarvisState(StrEnum):
    BOOTING = "booting"
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    WAITING_PERMISSION = "waiting_permission"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    SPEAKING = "speaking"
    ERROR = "error"


class StateTransitionError(RuntimeError):
    pass


class JarvisStateMachine:
    _ALLOWED = {
        JarvisState.BOOTING: {JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.IDLE: {
            JarvisState.LISTENING,
            JarvisState.UNDERSTANDING,
            JarvisState.PLANNING,
            JarvisState.EXECUTING,
            JarvisState.SPEAKING,
            JarvisState.ERROR,
        },
        JarvisState.LISTENING: {JarvisState.TRANSCRIBING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.TRANSCRIBING: {JarvisState.UNDERSTANDING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.UNDERSTANDING: {
            JarvisState.PLANNING,
            JarvisState.WAITING_PERMISSION,
            JarvisState.EXECUTING,
            JarvisState.SPEAKING,
            JarvisState.IDLE,
            JarvisState.ERROR,
        },
        JarvisState.PLANNING: {
            JarvisState.WAITING_PERMISSION,
            JarvisState.EXECUTING,
            JarvisState.IDLE,
            JarvisState.ERROR,
        },
        JarvisState.WAITING_PERMISSION: {JarvisState.EXECUTING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.EXECUTING: {JarvisState.VERIFYING, JarvisState.RECOVERING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.VERIFYING: {JarvisState.IDLE, JarvisState.RECOVERING, JarvisState.SPEAKING, JarvisState.ERROR},
        JarvisState.RECOVERING: {JarvisState.EXECUTING, JarvisState.VERIFYING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.SPEAKING: {JarvisState.LISTENING, JarvisState.IDLE, JarvisState.ERROR},
        JarvisState.ERROR: {JarvisState.RECOVERING, JarvisState.IDLE},
    }

    def __init__(self, events: EventBus, initial: JarvisState = JarvisState.BOOTING):
        self.events = events
        self._state = initial
        self._lock = threading.RLock()

    @property
    def state(self) -> JarvisState:
        with self._lock:
            return self._state

    def transition(self, target: JarvisState | str, *, reason: str = "", source: str = "core") -> JarvisState:
        target = JarvisState(target)
        with self._lock:
            previous = self._state
            if target == previous:
                return target
            if target not in self._ALLOWED[previous]:
                raise StateTransitionError(f"{previous.value} -> {target.value}")
            self._state = target
        self.events.publish(
            "assistant.state_changed",
            {"previous": previous.value, "state": target.value, "reason": reason},
            source=source,
            priority=100 if target is JarvisState.ERROR else 0,
        )
        return target

    def emergency_idle(self) -> None:
        with self._lock:
            previous = self._state
            self._state = JarvisState.IDLE
        self.events.publish(
            "assistant.state_changed",
            {"previous": previous.value, "state": "idle", "reason": "emergency_stop"},
            source="emergency",
            priority=1000,
        )

    def advance(
        self, target: JarvisState | str, *, reason: str = "observed_runtime_state", source: str = "runtime"
    ) -> JarvisState:
        """Move through the shortest legal path when an external subsystem reports state."""
        target = JarvisState(target)
        if target == self.state:
            return target
        frontier: list[tuple[JarvisState, list[JarvisState]]] = [(self.state, [])]
        visited = {self.state}
        while frontier:
            state, path = frontier.pop(0)
            for candidate in self._ALLOWED[state]:
                if candidate in visited:
                    continue
                if candidate == target:
                    for step in [*path, candidate]:
                        self.transition(step, reason=reason, source=source)
                    return target
                visited.add(candidate)
                frontier.append((candidate, [*path, candidate]))
        raise StateTransitionError(f"no path to {target.value}")
