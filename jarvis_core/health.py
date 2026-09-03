from __future__ import annotations
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from .events import EventBus


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"
    DISABLED = "DISABLED"
    RESTARTING = "RESTARTING"


@dataclass(slots=True)
class HealthRecord:
    component: str
    status: HealthStatus
    detail: str
    updated_at: str


class HealthManager:
    def __init__(self, events: EventBus):
        self._events = events
        self._records: dict[str, HealthRecord] = {}
        self._lock = threading.RLock()

    def report(self, component: str, status: HealthStatus | str, detail: str = "") -> HealthRecord:
        record = HealthRecord(component, HealthStatus(status), detail, datetime.now(timezone.utc).isoformat())
        with self._lock:
            previous = self._records.get(component)
            self._records[component] = record
        if previous is None or previous.status != record.status or previous.detail != detail:
            self._events.publish("health.changed", asdict(record), source=component)
        return record

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {name: asdict(record) for name, record in self._records.items()}
