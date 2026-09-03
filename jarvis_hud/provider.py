from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from capability_registry import CAPABILITIES
from settings_store import get_setting
from continuous_improvement import analyze_evaluations


class HUDSnapshotProvider:
    """Builds immutable, bounded HUD data without touching Qt widgets."""

    def __init__(self, runtime, metrics_path: Path, log_path: Path):
        self.runtime = runtime
        self.metrics_path = Path(metrics_path)
        self.log_path = Path(log_path)

    def snapshot(self) -> dict:
        missions = self.runtime.mission_store.recent(50)
        counts = Counter(row["status"] for row in missions)
        active = [row for row in missions if row["status"] in {"pending", "running", "paused", "incomplete"}]
        health = self.runtime.health.snapshot()
        performance = self._json(self.metrics_path)
        logs = self._logs(150)
        skills = self.runtime.skills.metrics()
        notifications = self._notifications(health, missions)
        companion = getattr(self.runtime, "companion", None)
        companion_snapshot = (
            companion.snapshot() if companion is not None else {"running": False, "mode": "passive", "available": False}
        )
        discovered = [{"id": key, "description": value, "source": "registry"} for key, value in CAPABILITIES.items()]
        known = {row["id"] for row in discovered}
        list_skills = getattr(self.runtime.skills, "list", None)
        for skill in (list_skills() if callable(list_skills) else []):
            skill_id = str(skill.get("name") or skill.get("id") or "").strip()
            if skill_id and skill_id not in known:
                discovered.append({"id": skill_id, "description": "Skill runtime registrata", "source": "runtime"})
        state_manager = getattr(self.runtime, "state", None)
        runtime_state = (
            state_manager.snapshot() if state_manager is not None and hasattr(state_manager, "snapshot") else {}
        )
        ai_metric = next(
            (
                row
                for name, row in performance.items()
                if isinstance(row, dict) and any(token in name.lower() for token in ("openai", "ai_response", "router"))
            ),
            {},
        )
        ai_health = next((row for name, row in health.items() if name.lower() in {"openai", "ai", "router"}), None)
        ai_status = str((ai_health or {}).get("status") or "UNKNOWN").upper()
        connected = (
            True
            if ai_status in {"HEALTHY", "READY", "ONLINE"}
            else False if ai_status in {"FAILED", "DEGRADED", "DISABLED"} else None
        )
        openai_state = {
            "model": get_setting("ai_model", ""),
            "latency_ms": ai_metric.get("average_ms"),
            "connected": connected,
            "status": ai_status,
        }
        memory_store = getattr(self.runtime, "memory", None)
        working_store = getattr(memory_store, "working", None)
        working_snapshot = getattr(working_store, "snapshot", None)
        memory = {
            "working": working_snapshot() if callable(working_snapshot) else {},
            "enabled": bool(get_setting("ai_memory", True)),
        }
        machine = getattr(self.runtime, "state_machine", None)
        assistant_state = getattr(getattr(machine, "state", None), "value", None)
        emergency = getattr(self.runtime, "emergency", None)
        broker = getattr(self.runtime, "broker", None)
        improvement = analyze_evaluations()
        context_engine = getattr(self.runtime, "context", None)
        context_snapshot = (
            context_engine.snapshot() if callable(getattr(context_engine, "snapshot", None)) else {}
        )
        return {
            "missions": {"counts": dict(counts), "active": active[:10], "recent": missions[:20]},
            "health": health,
            "performance": performance,
            "skill_metrics": skills,
            "logs": logs,
            "notifications": notifications,
            "voice": self.runtime.voice.snapshot(),
            "companion": companion_snapshot,
            "state": runtime_state,
            "assistant_state": assistant_state,
            "emergency": {"active": bool(getattr(emergency, "active", False))},
            "broker": {"healthy": bool(broker.health()) if broker is not None else False},
            "context": context_snapshot,
            "capabilities": discovered,
            "openai": openai_state,
            "memory": memory,
            "continuous_improvement": {
                "status": improvement.get("status"),
                "reports_considered": improvement.get("reports_considered", 0),
                "regressions": improvement.get("regressions", [])[:10],
                "recommendations": improvement.get("recommendations", [])[:5],
            },
        }

    @staticmethod
    def _notifications(health, missions):
        rows = []
        for name, state in health.items():
            if state["status"] in {"FAILED", "DEGRADED"}:
                rows.append({"priority": "high", "source": name, "message": state.get("detail") or state["status"]})
        for mission in missions:
            if mission["status"] in {"failed", "blocked"}:
                rows.append({"priority": "high", "source": "mission", "message": mission["objective"]})
        return rows[:20]

    @staticmethod
    def _json(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _logs(self, limit: int):
        if not self.log_path.exists():
            return []
        try:
            # Read only a bounded tail. The runtime log can grow to hundreds of
            # MB; loading the whole JSONL file freezes the Qt thread on LOG.
            with self.log_path.open("rb") as stream:
                stream.seek(0, 2)
                chunks = bytearray()
                cursor = stream.tell()
                while cursor > 0 and chunks.count(b"\n") <= limit:
                    step = min(64 * 1024, cursor)
                    cursor -= step
                    stream.seek(cursor)
                    chunks[:0] = stream.read(step)
                lines = bytes(chunks).decode("utf-8", errors="replace").splitlines()[-limit:]
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"event": line, "severity": "INFO"})
        return rows
