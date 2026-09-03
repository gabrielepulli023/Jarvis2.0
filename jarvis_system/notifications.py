from __future__ import annotations
import threading
import time
import uuid
from collections import deque
from typing import Any


class NotificationCenter:
    def __init__(self, events, limit: int = 100):
        self.events = events
        self._rows: deque[dict[str, Any]] = deque(maxlen=max(10, int(limit)))
        self._lock = threading.RLock()

    def notify(self, title: str, message: str, level: str = "info", request_id: str | None = None) -> dict:
        level = str(level).lower()
        if level not in {"info", "success", "warning", "error", "permission"}:
            raise ValueError("Livello notifica non valido")
        row = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": time.time(),
            "title": str(title)[:200],
            "message": str(message)[:2000],
            "level": level,
            "request_id": request_id,
        }
        with self._lock:
            self._rows.append(row)
        self.events.publish(
            "notification.created", row, source="notifications", priority=100 if level in {"error", "permission"} else 0
        )
        return dict(row)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._rows)
