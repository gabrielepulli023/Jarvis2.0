"""Canonical, validated mission planning over the existing skill registry."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class PlannedStep:
    id: str
    label: str
    action: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    expected: Mapping[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    timeout: float = 30.0
    max_attempts: int = 1
    risk: str = "safe"
    fallbacks: tuple[str, ...] = ()
    rollback: Mapping[str, Any] | None = None
    precondition: Mapping[str, Any] | None = None

    def as_dict(self):
        return redact(asdict(self))


@dataclass(frozen=True, slots=True)
class MissionPlan:
    objective: str
    success_criteria: tuple[str, ...]
    steps: tuple[PlannedStep, ...]
    source: str = "local"
    version: int = 1
    risk_summary: str = "safe"

    def as_dict(self):
        value = asdict(self)
        value["steps"] = [step.as_dict() for step in self.steps]
        return redact(value)


class MissionToolCatalogAdapter:
    def __init__(self, registry):
        self.registry = registry

    def names(self) -> set[str]:
        return {str(row.get("name")) for row in self.registry.list() if row.get("name")}

    def rows(self):
        return self.registry.list()[:80]

    def manifest(self, name: str) -> Mapping[str, Any] | None:
        for row in self.rows():
            if str(row.get("name")) == name:
                return row
        return None


class PlanValidator:
    MAX_STEPS = 12

    def __init__(self, catalog: MissionToolCatalogAdapter | set[str]):
        self.catalog = catalog if isinstance(catalog, MissionToolCatalogAdapter) else None
        self.names = catalog.names() if self.catalog else set(catalog)

    def validate(self, plan: MissionPlan | Mapping[str, Any]) -> MissionPlan:
        value = plan.as_dict() if isinstance(plan, MissionPlan) else dict(plan)
        rows = list(value.get("steps") or [])
        if not rows or len(rows) > self.MAX_STEPS:
            raise ValueError("invalid step count")
        ids = [str(row.get("id", "")) for row in rows]
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", item) for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique and bounded")
        known = set(ids)
        for row in rows:
            action = str(row.get("action") or row.get("tool") or "")
            if action not in self.names:
                raise ValueError(f"unknown action: {action}")
            manifest = self.catalog.manifest(action) if self.catalog else None
            declared_risk = str(row.get("risk", "safe"))
            actual_risk = str((manifest or {}).get("risk", "safe"))
            risk_order = {"safe": 0, "sensitive": 1, "admin": 2, "destructive": 3, "forbidden": 4}
            effective_risk = max((declared_risk, actual_risk), key=lambda item: risk_order[item])
            if effective_risk == "forbidden":
                raise ValueError(f"forbidden action: {action}")
            arguments = dict(row.get("arguments") or {})
            if manifest and manifest.get("inputs"):
                allowed = set(manifest["inputs"])
                if any(key not in allowed for key in arguments):
                    raise ValueError(f"invalid arguments: {action}")
            fallbacks = tuple(str(x) for x in row.get("fallbacks", ()))
            if any(x not in self.names for x in fallbacks):
                raise ValueError("unknown fallback")
            rollback = row.get("rollback")
            if rollback:
                if not isinstance(rollback, Mapping) or str(rollback.get("action")) not in self.names:
                    raise ValueError("unknown rollback")
            deps = tuple(str(x) for x in row.get("dependencies", ()))
            if not set(deps) <= known:
                raise ValueError("missing dependency")
            timeout = float(row.get("timeout", 30))
            attempts = int(row.get("max_attempts", 1))
            if not 0.01 <= timeout <= 900 or not 1 <= attempts <= 5:
                raise ValueError("step limits exceeded")
            if str(row.get("risk", "safe")) not in {"safe", "sensitive", "admin", "destructive", "forbidden"}:
                raise ValueError("invalid risk")
        self._check_cycles({str(row["id"]): set(row.get("dependencies", ())) for row in rows})
        steps = tuple(PlannedStep(str(row["id"]), str(row.get("label", row["id"]))[:200], str(row.get("action") or row.get("tool")), dict(row.get("arguments") or {}), dict(row.get("expected") or {}), tuple(str(x) for x in row.get("dependencies", ())), min(900.0, max(.01, float(row.get("timeout", 30)))), min(5, max(1, int(row.get("max_attempts", 1)))), max((str(row.get("risk", "safe")), str((self.catalog.manifest(str(row.get("action") or row.get("tool"))) or {}).get("risk", "safe"))), key=lambda item: {"safe": 0, "sensitive": 1, "admin": 2, "destructive": 3, "forbidden": 4}[item]), tuple(str(x) for x in row.get("fallbacks", ())), row.get("rollback"), row.get("precondition")) for row in rows)
        return MissionPlan(str(value.get("objective") or "")[:1000], tuple(str(x)[:300] for x in list(value.get("success_criteria") or [])[:8]), steps, str(value.get("source", "planner"))[:30], int(value.get("version", 1)), str(value.get("risk_summary", "safe"))[:30])

    @staticmethod
    def _check_cycles(graph):
        visiting, visited = set(), set()
        def walk(node):
            if node in visiting: raise ValueError("plan contains cycle")
            if node in visited: return
            visiting.add(node)
            for dep in graph[node]: walk(dep)
            visiting.remove(node); visited.add(node)
        for node in graph: walk(node)


class MissionPlanner:
    def __init__(self, catalog: MissionToolCatalogAdapter, validator: PlanValidator | None = None):
        self.catalog = catalog
        self.validator = validator or PlanValidator(catalog)

    def plan(self, objective: str, proposed: Mapping[str, Any] | None = None) -> MissionPlan:
        if proposed is None:
            raise ValueError("planner requires an executable structured plan")
        value = dict(proposed)
        value.setdefault("objective", objective)
        return self.validator.validate(value)
