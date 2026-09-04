"""Canonical, validated mission planning over the existing skill registry."""
from __future__ import annotations

import re
import json
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

    @classmethod
    def from_dict(cls, value):
        return cls(str(value["id"]), str(value.get("label", value["id"])), str(value.get("action") or value.get("tool")), dict(value.get("arguments") or {}), dict(value.get("expected") or {}), tuple(value.get("dependencies", ())), float(value.get("timeout", 30)), int(value.get("max_attempts", 1)), str(value.get("risk", "safe")), tuple(value.get("fallbacks", ())), value.get("rollback"), value.get("precondition"))


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

    @classmethod
    def from_dict(cls, value):
        return cls(str(value.get("objective") or value.get("goal") or ""), tuple(value.get("success_criteria") or ()), tuple(PlannedStep.from_dict(row) for row in (value.get("steps") or [])[:12]), str(value.get("source", "planner")), int(value.get("version", 1)), str(value.get("risk_summary", "safe")))


class MissionToolCatalogAdapter:
    def __init__(self, registry):
        self.registry = registry

    def names(self) -> set[str]:
        return {str(row.get("name")) for row in self.registry.list() if row.get("name")}

    def rows(self):
        return self.registry.list()[:80]

    def manifest(self, name: str) -> Mapping[str, Any] | None:
        manifest_lookup = getattr(self.registry, "manifest", None)
        manifest = manifest_lookup(name) if manifest_lookup else None
        if manifest is not None:
            row = {**asdict(manifest), "name": manifest.name, "risk": manifest.risk, "inputs": list(manifest.inputs)}
            return row
        return next((row for row in self.registry.list() if str(row.get("name")) == name), None)

    def prompt_rows(self, objective: str, limit: int = 40):
        words = set(str(objective).casefold().split())
        rows = self.registry.list()
        rows.sort(key=lambda row: (-sum(word in json.dumps(row, default=str).casefold() for word in words if len(word) > 2), str(row.get("name", ""))))
        return rows[:max(1, min(50, int(limit)))]


class MissionExecutionAdapter:
    """Explicit bridge: canonical mission actions use SkillRegistry names."""
    def __init__(self, registry):
        self.registry = registry

    def __call__(self, name: str, arguments: dict):
        result = self.registry.execute(str(name), **dict(arguments or {}))
        data = dict(getattr(result, "data", {}) or {})
        payload = {"successo": bool(getattr(result, "success", False)), "messaggio": str(getattr(result, "message", "") or ""), "dati": data, "skill": str(getattr(result, "skill", "") or name)}
        if isinstance(data.get("verification"), Mapping):
            payload["verification"] = dict(data["verification"])
        if getattr(result, "fallback_used", None):
            payload["fallback_used"] = result.fallback_used
        if data.get("requires_confirmation"):
            payload.update({"richiede_conferma": True, "azione_id": data.get("action_id"), "rischio": data.get("risk")})
        return payload


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
            self._validate_action(action, arguments)
            fallbacks = tuple(str(x) for x in row.get("fallbacks", ()))
            if any(x not in self.names for x in fallbacks):
                raise ValueError("unknown fallback")
            rollback = row.get("rollback")
            if rollback:
                if not isinstance(rollback, Mapping) or str(rollback.get("action")) not in self.names:
                    raise ValueError("unknown rollback")
                self._validate_action(str(rollback["action"]), dict(rollback.get("arguments") or {}))
            precondition = row.get("precondition")
            if precondition:
                if not isinstance(precondition, Mapping) or str(precondition.get("action")) not in self.names:
                    raise ValueError("unknown precondition")
                pre_name = str(precondition["action"])
                pre_manifest = self.catalog.manifest(pre_name) if self.catalog else None
                if str((pre_manifest or {}).get("risk", "safe")) == "forbidden":
                    raise ValueError("forbidden precondition")
                self._validate_action(pre_name, dict(precondition.get("arguments") or {}))
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

    def _validate_action(self, name: str, arguments: dict) -> None:
        validator = getattr(getattr(self.catalog, "registry", None), "validate_arguments", None)
        if validator:
            diagnostics = validator(name, arguments)
            if diagnostics:
                raise ValueError(f"invalid arguments: {name}")
        for key, item in arguments.items():
            if isinstance(item, Mapping) and set(item) == {"$ref"}:
                ref = item["$ref"]
                if not isinstance(ref, Mapping) or not isinstance(ref.get("step"), str) or not isinstance(ref.get("path", ""), str) or any(token.casefold() in {"password", "token", "api_key", "authorization", "cookie", "secret"} for token in str(ref.get("path", "")).split(".")):
                    raise ValueError(f"invalid output reference: {key}")

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

    def plan_with_model(self, client, model, objective: str, context: str = "") -> MissionPlan:
        prompt = {"objective": str(objective)[:1000], "context": str(context)[:4000], "capabilities": self.catalog.prompt_rows(objective)}
        response = client.responses.create(model=model, instructions="Produci solo JSON strutturato, senza reasoning.", input=json.dumps(prompt, ensure_ascii=False), reasoning={"effort": "medium"})
        import json as _json
        return self.plan(objective, _json.loads(response.output_text))
