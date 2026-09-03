"""Mission reliability telemetry with bounded, privacy-safe persistence.

This is deliberately independent of providers and UI: callers can attach it to
the existing mission/event bus without creating a second execution pipeline.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import data_path


_SENSITIVE = ("key", "token", "password", "secret", "authorization", "prompt", "transcript", "content")


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if any(part in str(k).lower() for part in _SENSITIVE) else _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value[:32]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) or len(value) <= 160 else value[:157] + "..."
    return str(value)[:160]


class ReliabilityEngine:
    """Thread-safe mission recorder; persistence is atomic and bounded."""

    def __init__(self, store: Path | None = None, version: str = "unknown", history_limit: int = 2048):
        self.store = store or data_path("reliability", "missions.json")
        self.version = version
        self.history_limit = max(1, history_limit)
        self._lock = threading.RLock()
        self._missions: deque[dict[str, Any]] = deque(maxlen=self.history_limit)
        self._active: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.store.read_text(encoding="utf-8")) if self.store.exists() else []
            if isinstance(raw, list):
                self._missions.extend(item for item in raw if isinstance(item, dict))
        except (OSError, json.JSONDecodeError):
            return

    def _persist(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(self.store.suffix + ".tmp")
        tmp.write_text(json.dumps(list(self._missions), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.store)

    def start(self, goal: str, *, confidence: float = 0.0, provider: str | None = None, **fields: Any) -> str:
        mission_id = uuid.uuid4().hex
        now = time.monotonic()
        with self._lock:
            self._active[mission_id] = {"mission_id": mission_id, "version": self.version, "goal": _safe(goal), "started_at": datetime.now(timezone.utc).isoformat(), "_started": now, "status": "started", "confidence_initial": max(0.0, min(1.0, confidence)), "provider": provider, "retries": 0, "fallbacks": [], "tools": [], "tool_failures": 0, "ai_calls": 0, "tool_calls": 0, **_safe(fields)}
        return mission_id

    def event(self, mission_id: str, event_name: str, **fields: Any) -> bool:
        with self._lock:
            mission = self._active.get(mission_id)
            if not mission:
                return False
            mission.setdefault("events", []).append({"name": event_name, "at": time.monotonic(), **_safe(fields)})
            if event_name == "retry": mission["retries"] += 1
            if event_name == "fallback": mission["fallbacks"].append(_safe(fields.get("provider", "unknown")))
            if event_name == "tool":
                mission["tool_calls"] += 1; mission["tools"].append(_safe(fields.get("name", "unknown")))
                if not fields.get("success", False): mission["tool_failures"] += 1
            if event_name == "ai_call": mission["ai_calls"] += 1
            return True

    def finish(self, mission_id: str, status: str = "completed", *, confidence: float = 0.0, verified: bool = False, error_category: str | None = None, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            mission = self._active.pop(mission_id, None)
            if not mission: return None
            mission.update({"status": status, "finished_at": datetime.now(timezone.utc).isoformat(), "duration_ms": round((time.monotonic() - mission.pop("_started")) * 1000, 2), "confidence_final": max(0.0, min(1.0, confidence)), "post_action_verified": bool(verified), "error_category": error_category, **_safe(fields)})
            self._missions.append(mission); self._persist(); return dict(mission)

    def report(self, version: str | None = None) -> dict[str, Any]:
        with self._lock:
            rows = [r for r in self._missions if version is None or r.get("version") == version]
            completed = [r for r in rows if r.get("status") == "completed"]
            recovery = [r for r in rows if r.get("retries", 0) or r.get("fallbacks")]
            durations = [r["duration_ms"] for r in rows if isinstance(r.get("duration_ms"), (int, float))]
            total_tools = sum(r.get("tool_calls", 0) for r in rows)
            failures = sum(r.get("tool_failures", 0) for r in rows)
            return {"version": version or "all", "missions": len(rows), "kpi": {"task_success_rate": round(len(completed) / len(rows), 3) if rows else 0.0, "first_attempt_success_rate": round(sum(r.get("retries", 0) == 0 and r.get("status") == "completed" for r in rows) / len(rows), 3) if rows else 0.0, "recovery_rate": round(sum(r.get("status") == "completed" for r in recovery) / len(recovery), 3) if recovery else 0.0, "tool_failure_rate": round(failures / total_tools, 3) if total_tools else 0.0, "mean_time_to_complete_ms": round(sum(durations) / len(durations), 2) if durations else 0.0}, "status_counts": dict(Counter(r.get("status", "unknown") for r in rows)), "active": len(self._active)}
