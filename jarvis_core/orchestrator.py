"""Objective orchestration over the existing planner, registry and verifier.

This module deliberately does not execute tools itself.  The operational brain
continues to own the router/tool loop; this component supplies capability
selection context and keeps a bounded, evidence-based mission trace.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrchestrationTrace:
    objective: str
    plan: dict[str, Any]
    run_id: str
    status: str = "running"
    steps: list[dict[str, Any]] = field(default_factory=list)
    selected_capabilities: list[str] = field(default_factory=list)
    recovery_requests: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class AutonomousOrchestrator:
    """Coordinate objective context without creating a second execution stack."""

    def __init__(self, registry, state=None, max_traces: int = 32):
        self.registry = registry
        self.state = state
        self.max_traces = max(4, int(max_traces))
        self._traces: dict[str, OrchestrationTrace] = {}
        self._lock = threading.RLock()
        self._counter = 0

    def capability_catalog(self, objective: str = "", limit: int = 80) -> list[dict[str, Any]]:
        """Return the registry metadata most relevant to an objective."""
        words = {word for word in str(objective or "").casefold().split() if len(word) > 2}
        rows = self.registry.list()

        def score(row):
            haystack = " ".join(
                [str(row.get("name", "")), str(row.get("capability", "")), str(row.get("description", ""))]
                + [str(x) for x in row.get("intents", ())]
            ).casefold()
            return sum(word in haystack for word in words)

        rows.sort(key=lambda row: (-score(row), str(row.get("name", ""))))
        selected = []
        for row in rows[: max(1, int(limit))]:
            selected.append(
                {
                    key: row.get(key)
                    for key in (
                        "name", "capability", "inputs", "outputs", "side_effects", "cost", "latency",
                        "online", "execution", "confidence", "requires_confirmation", "prerequisites",
                        "fallback_capabilities",
                    )
                }
            )
        return selected

    def planning_context(self, objective: str, plan: dict[str, Any] | None = None) -> str:
        payload = {
            "objective": str(objective or "")[:1000],
            "plan": plan or {},
            "available_capabilities": self.capability_catalog(objective),
            "policy": "Scegli skill read-only sicure liberamente; mantieni conferme per side effect sensibili.",
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def begin(self, objective: str, plan: dict[str, Any] | None = None, *, run_id: str | None = None) -> str:
        with self._lock:
            self._counter += 1
            trace_id = str(run_id or f"mission-{int(time.time() * 1000):x}-{self._counter:x}")[:128]
            trace = OrchestrationTrace(str(objective or "")[:1000], dict(plan or {}), trace_id)
            self._traces[trace_id] = trace
            while len(self._traces) > self.max_traces:
                oldest = min(self._traces.values(), key=lambda item: item.started_at)
                self._traces.pop(oldest.run_id, None)
        self._publish(trace)
        return trace_id

    def observe(self, run_id: str, tool: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
        """Record one tool observation and derive a safe recovery hint."""
        with self._lock:
            trace = self._traces.get(str(run_id))
            if trace is None:
                return {"status": "unknown_run", "recovery": None}
            value = self._result_dict(result)
            data = value.get("data", value.get("dati", {}))
            if not isinstance(data, dict):
                data = {}
            verification = value.get("verification")
            verified = bool(
                isinstance(verification, dict) and verification.get("status") == "verified"
            ) or data.get("verified") is True
            success = bool(value.get("success", value.get("successo", False)))
            skill_name = str(value.get("skill") or (arguments or {}).get("skill") or tool)
            manifest = self.registry.manifest(skill_name)
            recovery = None
            if not success:
                fallback_names = tuple(manifest.fallbacks) if manifest else ()
                fallback_caps = tuple(manifest.fallback_capabilities) if manifest else ()
                if not fallback_caps:
                    fallback_caps = tuple(
                        self.registry.manifest(name).capability
                        for name in fallback_names
                        if self.registry.manifest(name) is not None
                    )
                if fallback_names or fallback_caps:
                    recovery = {
                        "action": "retry_or_fallback",
                        "failed_skill": skill_name,
                        "fallback_skills": list(fallback_names),
                        "fallback_capabilities": list(fallback_caps),
                    }
                    trace.recovery_requests += 1
            status = "verified" if success and verified else ("unverified" if success else "failed")
            row = {
                "tool": str(tool),
                "skill": skill_name,
                "status": status,
                "success": success,
                "verification": verification if isinstance(verification, dict) else None,
                "message": str(value.get("message", value.get("messaggio", "")) or "")[:500],
                "fallback_used": value.get("fallback_used"),
                "observed_at": time.time(),
            }
            trace.steps.append(row)
            if skill_name and skill_name not in trace.selected_capabilities:
                capability = manifest.capability if manifest else ""
                if capability and capability not in trace.selected_capabilities:
                    trace.selected_capabilities.append(capability)
            if recovery:
                trace.status = "recovering"
            self._publish(trace)
            return {"status": status, "recovery": recovery}

    def recovery_instruction(self, run_id: str) -> str:
        with self._lock:
            trace = self._traces.get(str(run_id))
            if not trace:
                return ""
            failed = [step for step in trace.steps if step["status"] == "failed"][-3:]
            if not failed:
                return ""
            return (
                "Il passaggio precedente non è riuscito. Valuta un retry mirato o una capability alternativa "
                "dal catalogo; non dichiarare completato l'obiettivo finché la verifica non è positiva."
            )

    def finish(self, run_id: str, status: str, summary: str) -> dict[str, Any]:
        with self._lock:
            trace = self._traces.get(str(run_id))
            if trace is None:
                return {"status": "unknown_run"}
            trace.status = str(status)
            trace.finished_at = time.time()
            result = self.snapshot(run_id)
        self._publish(trace)
        return {**result, "summary": str(summary or "")[:2000]}

    def snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            trace = self._traces.get(str(run_id)) if run_id else None
            if trace is None and self._traces:
                trace = max(self._traces.values(), key=lambda item: item.started_at)
            if trace is None:
                return {}
            return {
                "run_id": trace.run_id,
                "objective": trace.objective,
                "status": trace.status,
                "steps": list(trace.steps[-30:]),
                "selected_capabilities": list(trace.selected_capabilities),
                "recovery_requests": trace.recovery_requests,
                "started_at": trace.started_at,
                "finished_at": trace.finished_at,
            }

    @staticmethod
    def _result_dict(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return dict(result)
        return {
            "success": bool(getattr(result, "success", False)),
            "message": str(getattr(result, "message", "") or ""),
            "data": dict(getattr(result, "data", {}) or {}),
            "skill": str(getattr(result, "skill", "") or ""),
            "fallback_used": getattr(result, "fallback_used", None),
        }

    def _publish(self, trace: OrchestrationTrace) -> None:
        if self.state is None:
            return
        try:
            self.state.set("orchestration", self.snapshot(trace.run_id), source="orchestrator")
        except Exception:
            # Observability must never interrupt the operational path.
            return
