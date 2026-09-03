from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class Event:
    topic: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "core"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    priority: int = 0
    confidence: float = 1.0
    deduplication_key: str | None = None

    @property
    def type(self) -> str:
        return self.topic


class EventBus:
    """Thread-safe in-process pub/sub bus with isolated subscribers."""

    def __init__(self, logger: logging.Logger | None = None):
        self._subscribers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._logger = logger or logging.getLogger("jarvis.events")

    def subscribe(self, topic: str, callback: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers[topic].append(callback)

        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(topic, [])
                if callback in callbacks:
                    callbacks.remove(callback)

        return unsubscribe

    def publish(
        self,
        topic: str,
        payload: dict[str, Any] | None = None,
        *,
        source: str = "core",
        priority: int = 0,
        confidence: float = 1.0,
        deduplication_key: str | None = None,
    ) -> Event:
        event = Event(
            topic=topic,
            payload=dict(payload or {}),
            source=source,
            priority=int(priority),
            confidence=max(0.0, min(1.0, float(confidence))),
            deduplication_key=deduplication_key,
        )
        with self._lock:
            callbacks = tuple(self._subscribers.get(topic, ())) + tuple(self._subscribers.get("*", ()))
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                self._logger.exception("event_subscriber_failed", extra={"topic": topic})
        return event
