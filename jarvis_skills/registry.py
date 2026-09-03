from __future__ import annotations
import inspect
import json
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, List
from jarvis_core.logging import redact


def normalize_trigger_text(value: Any) -> str:
    """Normalize user text and manifest triggers to the same token space."""
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


class Capability(StrEnum):
    READ_SCREEN = "READ_SCREEN"
    CONTROL_MOUSE = "CONTROL_MOUSE"
    CONTROL_KEYBOARD = "CONTROL_KEYBOARD"
    READ_FILES = "READ_FILES"
    WRITE_FILES = "WRITE_FILES"
    PROCESS_CONTROL = "PROCESS_CONTROL"
    NETWORK = "NETWORK"
    BROWSER_CONTROL = "BROWSER_CONTROL"
    SYSTEM_SETTINGS = "SYSTEM_SETTINGS"


def _infer_capability(permissions, entrypoint="") -> str:
    """Provide stable planner metadata for legacy manifests."""
    value = str(entrypoint or "").casefold()
    if any(token in value for token in ("searx", "search", "crawl", "web")):
        return "web_search"
    if any(token in value for token in ("openhands", "ruff", "test", "project", "code")):
        return "software_engineering"
    if "screenpipe" in value:
        return "screen_history_search"
    if "qdrant" in value or "memory" in value:
        return "memory"
    if "watchdog" in value or "file" in value:
        return "filesystem"
    permission_values = {getattr(item, "value", str(item)) for item in permissions or ()}
    if "BROWSER_CONTROL" in permission_values:
        return "browser_control"
    if "READ_SCREEN" in permission_values:
        return "screen_observation"
    if "WRITE_FILES" in permission_values:
        return "filesystem_write"
    if "READ_FILES" in permission_values:
        return "filesystem_read"
    if "NETWORK" in permission_values:
        return "network"
    return "general_assistance"


@dataclass(frozen=True, slots=True)
class SkillManifest:
    name: str
    version: str
    description: str
    intents: tuple[str, ...]
    permissions: frozenset[Capability]
    entrypoint: str
    requirements: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    risk: str = "safe"
    timeout: float = 30.0
    retries: int = 0
    verification_strategy: str = "handler_result"
    # Planner-facing metadata.  These fields extend the existing manifest so
    # the registry remains the single source of truth for capabilities.
    capability: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    cost: str = "low"
    latency: str = "low"
    online: bool = False
    execution: str = "local"
    confidence: float = 1.0
    requires_confirmation: bool = False
    prerequisites: tuple[str, ...] = ()
    fallback_capabilities: tuple[str, ...] = ()

    def __post_init__(self):
        if self.risk not in {"safe", "sensitive", "admin", "destructive", "forbidden"}:
            raise ValueError(f"invalid risk: {self.risk}")
        if not 0.01 <= float(self.timeout) <= 3600:
            raise ValueError("invalid timeout")
        if not 0 <= int(self.retries) <= 10:
            raise ValueError("invalid retries")
        # Legacy callers may construct the dataclass directly.  ``register``
        # enriches those manifests before they become planner-visible.
        if self.cost not in {"low", "medium", "high"}:
            raise ValueError("invalid cost")
        if self.latency not in {"low", "medium", "high"}:
            raise ValueError("invalid latency")
        if self.execution not in {"local", "cloud", "hybrid"}:
            raise ValueError("invalid execution")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("invalid confidence")

    @classmethod
    def from_dict(cls, data: dict):
        required = ("name", "version", "description", "intents", "permissions", "entrypoint")
        missing = [x for x in required if not data.get(x)]
        if missing:
            raise ValueError(f"missing manifest fields: {missing}")
        return cls(
            name=str(data["name"]),
            version=str(data["version"]),
            description=str(data["description"]),
            intents=tuple(map(str, data["intents"])),
            permissions=frozenset(Capability(x) for x in data["permissions"]),
            entrypoint=str(data["entrypoint"]),
            requirements=tuple(map(str, data.get("requirements", ()))),
            tests=tuple(map(str, data.get("tests", ()))),
            fallbacks=tuple(map(str, data.get("fallbacks", ()))),
            risk=str(data.get("risk", "safe")),
            timeout=float(data.get("timeout", 30)),
            retries=int(data.get("retries", 0)),
            verification_strategy=str(data.get("verification_strategy", "handler_result")),
            capability=str(data.get("capability") or _infer_capability(data.get("permissions", ()), data.get("entrypoint", ""))),
            inputs=tuple(map(str, data.get("inputs", ()))),
            outputs=tuple(map(str, data.get("outputs", ()))),
            side_effects=tuple(map(str, data.get("side_effects", ()))),
            cost=str(data.get("cost", "low")),
            latency=str(data.get("latency", "low")),
            online=bool(data.get("online", False)),
            execution=str(data.get("execution", "local")),
            confidence=float(data.get("confidence", 1.0)),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            prerequisites=tuple(map(str, data.get("prerequisites", ()))),
            fallback_capabilities=tuple(map(str, data.get("fallback_capabilities", ()))),
        )


@dataclass(frozen=True, slots=True)
class SkillResult:
    success: bool
    message: str
    data: dict = field(default_factory=dict)
    skill: str = ""
    fallback_used: str | None = None


class SkillRegistry:
    def __init__(
        self,
        metrics_path: Path,
        authorize: Callable[[Capability], bool] | None = None,
        authorize_risk: Callable[..., str] | None = None,
        audit: Callable[..., object] | None = None,
    ):
        self._manifests: dict[str, SkillManifest] = {}
        self._handlers: dict[str, Callable[..., SkillResult | dict]] = {}
        self._authorize = authorize or (lambda capability: "deny")
        self._authorize_risk = authorize_risk or (lambda manifest: "allow")
        self._audit = audit
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.metrics_path = Path(metrics_path)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _enrich_manifest(self, manifest: SkillManifest, handler=None) -> SkillManifest:
        """Normalize legacy manifests into planner-ready metadata."""
        permissions = set(manifest.permissions)
        capability = manifest.capability or _infer_capability(permissions, manifest.entrypoint)
        if handler is not None and not manifest.inputs:
            try:
                inputs = tuple(
                    parameter.name
                    for parameter in inspect.signature(handler).parameters.values()
                    if parameter.kind
                    in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
                )
            except (TypeError, ValueError):
                inputs = ()
        else:
            inputs = manifest.inputs
        side_effects = manifest.side_effects
        if not side_effects:
            side_effects = () if not permissions.intersection(
                {Capability.WRITE_FILES, Capability.CONTROL_MOUSE, Capability.CONTROL_KEYBOARD,
                 Capability.PROCESS_CONTROL, Capability.SYSTEM_SETTINGS}
            ) else ("filesystem" if Capability.WRITE_FILES in permissions else "computer")
        online = bool(manifest.online or Capability.NETWORK in permissions)
        execution = manifest.execution
        if execution == "local" and online:
            execution = "hybrid" if any(token in manifest.entrypoint.casefold() for token in ("runtime", "browser", "integration")) else "cloud"
        cost = manifest.cost
        if cost == "low" and (manifest.risk in {"admin", "destructive"} or manifest.timeout >= 300):
            cost = "high"
        latency = manifest.latency
        if latency == "low" and manifest.timeout >= 120:
            latency = "high"
        return replace(
            manifest,
            capability=capability,
            inputs=inputs,
            outputs=manifest.outputs or ("success", "message", "data", "verification"),
            side_effects=side_effects or ("none",),
            cost=cost,
            latency=latency,
            online=online,
            execution=execution,
            confidence=max(0.0, min(float(manifest.confidence), 1.0)),
            requires_confirmation=bool(manifest.requires_confirmation or manifest.risk != "safe"),
            prerequisites=manifest.prerequisites or manifest.requirements,
        )

    def _migrate(self):
        with closing(sqlite3.connect(self.metrics_path)) as db:
            with db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS skill_metrics(skill TEXT PRIMARY KEY,uses INTEGER NOT NULL DEFAULT 0,successes INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,timeouts INTEGER NOT NULL DEFAULT 0,fallbacks INTEGER NOT NULL DEFAULT 0,total_duration_ms INTEGER NOT NULL DEFAULT 0,last_execution TEXT)"""
                )

    def register(self, manifest: SkillManifest, handler: Callable[..., SkillResult | dict]) -> None:
        manifest = self._enrich_manifest(manifest, handler)
        with self._lock:
            if manifest.name in self._manifests and self._manifests[manifest.name].version != manifest.version:
                raise ValueError(f"skill already registered with another version: {manifest.name}")
            self._manifests[manifest.name] = manifest
            self._handlers[manifest.name] = handler

    def _risk_decision(self, manifest: SkillManifest, arguments: dict[str, Any]) -> str:
        """Evaluate risk with arguments while preserving one-argument callbacks."""
        callback = self._authorize_risk
        try:
            parameters = tuple(inspect.signature(callback).parameters.values())
        except (TypeError, ValueError):
            return callback(manifest)
        accepts_arguments = any(parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters) or sum(
            parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            for parameter in parameters
        ) >= 2
        return callback(manifest, dict(arguments)) if accepts_arguments else callback(manifest)

    def _capability_decision(self, capability: Capability) -> str:
        """Normalize legacy boolean gates while preserving allow/confirm/deny."""
        decision = self._authorize(capability)
        if isinstance(decision, bool):
            return "allow" if decision else "deny"
        return str(decision).lower().strip() if str(decision).lower().strip() in {"allow", "confirm", "deny"} else "deny"

    def _capability_decisions(self, manifest: SkillManifest) -> dict[Capability, str]:
        return {capability: self._capability_decision(capability) for capability in manifest.permissions}

    def validate_arguments(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Validate a skill call before invoking its Python handler.

        Registered handler signatures are the canonical schema for Expansion
        skills.  Returning structured diagnostics here keeps malformed model
        calls out of the handler, where they would otherwise become a noisy
        ``TypeError`` and be mistaken for an execution failure.
        """
        handler = self._handlers.get(name)
        if handler is None:
            return None
        supplied = dict(arguments or {})
        try:
            parameters = inspect.signature(handler).parameters
        except (TypeError, ValueError):
            return None
        accepts_keywords = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        required = {
            parameter.name
            for parameter in parameters.values()
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            and parameter.default is inspect.Parameter.empty
        }
        missing = sorted(required - supplied.keys())
        unexpected = sorted(key for key in supplied if key not in parameters and not accepts_keywords)
        positional_only = sorted(
            parameter.name
            for parameter in parameters.values()
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY and parameter.name in supplied
        )
        if not missing and not unexpected and not positional_only:
            return None
        details: dict[str, Any] = {
            "error": "invalid_tool_arguments",
            "invocation_not_started": True,
        }
        if missing:
            details["missing_required_arguments"] = missing
        if unexpected:
            details["unexpected_arguments"] = unexpected
        if positional_only:
            details["positional_only_arguments"] = positional_only
        return details

    def load_manifests(self, root: Path) -> List[str]:
        loaded = []
        for path in Path(root).rglob("skill.json"):
            manifest = SkillManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            self._manifests[manifest.name] = self._enrich_manifest(manifest)
            loaded.append(manifest.name)
        return loaded

    def list(self) -> List[dict]:
        with self._lock:
            rows = []
            for manifest in self._manifests.values():
                row = {**asdict(manifest), "permissions": sorted(x.value for x in manifest.permissions)}
                if not row["fallback_capabilities"]:
                    row["fallback_capabilities"] = [
                        self._manifests[name].capability
                        for name in manifest.fallbacks
                        if name in self._manifests
                    ]
                rows.append(row)
            return rows

    def manifest(self, name: str) -> SkillManifest | None:
        with self._lock:
            return self._manifests.get(str(name))

    def match_intents(self, text: str, names: set[str] | frozenset[str] | None = None) -> list[dict[str, Any]]:
        """Return manifest-backed trigger matches, ordered by specificity.

        Matching is deliberately phrase-based and accent-insensitive.  The
        registry remains the single source of truth: callers can restrict the
        result to a capability family (for example Expansion) without keeping
        a second, drift-prone trigger whitelist in a router.
        """
        normalized_text = normalize_trigger_text(text)
        if not normalized_text:
            return []
        padded_text = f" {normalized_text} "
        allowed = set(names) if names is not None else None
        matches: list[dict[str, Any]] = []
        with self._lock:
            manifests = list(self._manifests.values())
        for manifest in manifests:
            if allowed is not None and manifest.name not in allowed:
                continue
            for intent in manifest.intents:
                normalized_intent = normalize_trigger_text(intent)
                if not normalized_intent or f" {normalized_intent} " not in padded_text:
                    continue
                matches.append(
                    {
                        "skill": manifest.name,
                        "intent": intent,
                        "normalized_intent": normalized_intent,
                        "token_count": len(normalized_intent.split()),
                        "character_count": len(normalized_intent),
                        "entrypoint": manifest.entrypoint,
                    }
                )
        return sorted(
            matches,
            key=lambda item: (-item["token_count"], -item["character_count"], item["skill"], item["intent"]),
        )

    def best_intent_match(self, text: str, names: set[str] | frozenset[str] | None = None) -> dict[str, Any] | None:
        matches = self.match_intents(text, names)
        return matches[0] if matches else None

    def execute(self, name: str, **arguments) -> SkillResult:
        manifest = self._manifests.get(name)
        if not manifest:
            return SkillResult(False, f"Skill non registrata: {name}", skill=name)
        capability_decisions = self._capability_decisions(manifest)
        denied = [x.value for x, decision in capability_decisions.items() if decision == "deny"]
        if denied:
            result = SkillResult(False, f"Permessi negati: {', '.join(sorted(denied))}", skill=name)
            self._audit_decision(manifest, arguments, result, "deny")
            return result
        invalid_arguments = self.validate_arguments(name, arguments)
        if invalid_arguments:
            result = SkillResult(
                False,
                "Argomenti tool non validi: " + ", ".join(
                    invalid_arguments.get("missing_required_arguments", [])
                    or invalid_arguments.get("unexpected_arguments", [])
                    or invalid_arguments.get("positional_only_arguments", [])
                ),
                invalid_arguments,
                skill=name,
            )
            self._audit_decision(manifest, arguments, result, "schema_error")
            return result
        risk_decision = self._risk_decision(manifest, arguments)
        if risk_decision == "deny":
            result = SkillResult(False, "Azione bloccata dalla policy di rischio.", {"risk": manifest.risk}, skill=name)
            self._audit_decision(manifest, arguments, result, "deny")
            return result
        if risk_decision == "confirm" or "confirm" in capability_decisions.values():
            effective_risk = manifest.risk if manifest.risk != "safe" else "sensitive"
            action_id = uuid.uuid4().hex[:12]
            created = time.time()
            with self._lock:
                self._pending[action_id] = {
                    "action_id": action_id,
                    "name": name,
                    "skill": name,
                    "arguments": dict(arguments),
                    "risk": effective_risk,
                    "created": created,
                    "timestamp": created,
                    "state": "pending_confirmation",
                }
            result = SkillResult(
                False,
                "Conferma utente richiesta.",
                {"requires_confirmation": True, "action_id": action_id, "risk": effective_risk},
                skill=name,
            )
            self._audit_decision(manifest, arguments, result, "waiting_confirmation", action_id)
            return result
        return self._execute_allowed(name, arguments)

    def _purge_pending_locked(self, max_age: float) -> None:
        cutoff = time.time() - max(0.0, float(max_age))
        for pending_id, row in list(self._pending.items()):
            if row.get("created", 0) < cutoff:
                self._pending.pop(pending_id, None)

    def pending(self, max_age: float = 300) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._purge_pending_locked(max_age)
            return {key: dict(value) for key, value in self._pending.items()}

    def cancel(self, action_id: str, max_age: float = 300) -> dict[str, Any] | None:
        with self._lock:
            pending = self._pending.pop(str(action_id), None)
        if not pending or time.time() - pending["created"] > max_age:
            return None
        return dict(pending)

    def confirm(self, action_id: str, max_age: float = 300) -> SkillResult:
        with self._lock:
            pending = self._pending.pop(str(action_id), None)
        if not pending or time.time() - pending["created"] > max_age:
            return SkillResult(False, "Conferma scaduta o inesistente.")
        manifest = self._manifests.get(pending["name"])
        if manifest is None or manifest.risk == "forbidden":
            return SkillResult(False, "Azione non confermabile.", skill=pending["name"])
        denied = [x.value for x in manifest.permissions if self._capability_decision(x) == "deny"]
        if denied:
            return SkillResult(False, f"Permessi negati: {', '.join(sorted(denied))}", skill=pending["name"])
        return self._execute_allowed(pending["name"], pending["arguments"])

    def _execute_allowed(self, name: str, arguments: dict) -> SkillResult:
        manifest = self._manifests[name]
        result = self._attempt(name, arguments)
        for _ in range(manifest.retries):
            if result.success:
                break
            result = self._attempt(name, arguments)
        if result.success:
            return result
        for fallback in manifest.fallbacks:
            fallback_manifest = self._manifests.get(fallback)
            if fallback_manifest is None:
                continue
            fallback_decisions = self._capability_decisions(fallback_manifest)
            fallback_denied = [x.value for x, decision in fallback_decisions.items() if decision == "deny"]
            if (
                fallback_denied
                or "confirm" in fallback_decisions.values()
                or self._risk_decision(fallback_manifest, arguments) != "allow"
            ):
                continue
            fallback_result = self._attempt(fallback, arguments, fallback_used=fallback)
            if fallback_result.success:
                return fallback_result
        return result

    def _attempt(self, name: str, arguments: dict, fallback_used: str | None = None) -> SkillResult:
        handler = self._handlers.get(name)
        manifest = self._manifests[name]
        started = time.perf_counter()
        if handler is None:
            return SkillResult(False, f"Entrypoint non collegato: {name}", skill=name, fallback_used=fallback_used)
        timeout = False
        try:
            value = handler(**arguments)
            result = (
                SkillResult(
                    value.success,
                    value.message,
                    dict(value.data),
                    value.skill or name,
                    fallback_used or value.fallback_used,
                )
                if isinstance(value, SkillResult)
                else SkillResult(
                    bool(value.get("success", value.get("successo", False))),
                    str(value.get("message", value.get("messaggio", ""))),
                    dict(value.get("data", value.get("dati", {})) or {}),
                    name,
                    fallback_used,
                )
            )
        except TimeoutError as exc:
            timeout = True
            result = SkillResult(False, redact(str(exc)), skill=name, fallback_used=fallback_used)
        except Exception as exc:
            result = SkillResult(False, redact(f"{type(exc).__name__}: {exc}"), skill=name, fallback_used=fallback_used)
        duration = int((time.perf_counter() - started) * 1000)
        self._record(name, result.success, duration, timeout, bool(fallback_used))
        if self._audit:
            self._audit(
                request_id=uuid.uuid4().hex,
                user_command="",
                planner_decision={"entrypoint": manifest.entrypoint, "fallback": fallback_used},
                tool=name,
                arguments=arguments,
                risk=manifest.risk,
                permission="allow",
                result={"success": result.success, "message": result.message, "data": result.data},
                duration_ms=duration,
                verification=manifest.verification_strategy,
            )
        return result

    def _record(self, name: str, success: bool, duration: int, timeout: bool, fallback: bool):
        from datetime import datetime, timezone

        with closing(sqlite3.connect(self.metrics_path)) as db:
            with db:
                db.execute(
                    """INSERT INTO skill_metrics VALUES(?,1,?,?,?,?,?,?) ON CONFLICT(skill) DO UPDATE SET uses=uses+1,successes=successes+excluded.successes,failures=failures+excluded.failures,timeouts=timeouts+excluded.timeouts,fallbacks=fallbacks+excluded.fallbacks,total_duration_ms=total_duration_ms+excluded.total_duration_ms,last_execution=excluded.last_execution""",
                    (
                        name,
                        int(success),
                        int(not success),
                        int(timeout),
                        int(fallback),
                        duration,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def metrics(self) -> List[dict]:
        with closing(sqlite3.connect(self.metrics_path)) as db:
            db.row_factory = sqlite3.Row
            with db:
                rows = db.execute(
                    "SELECT *,CASE WHEN uses=0 THEN 0 ELSE total_duration_ms*1.0/uses END average_duration_ms FROM skill_metrics ORDER BY uses DESC"
                ).fetchall()
        return [dict(x) for x in rows]

    def _audit_decision(self, manifest, arguments, result, permission, request_id=None):
        if self._audit:
            self._audit(
                request_id=request_id or uuid.uuid4().hex,
                user_command="",
                planner_decision={"entrypoint": manifest.entrypoint},
                tool=manifest.name,
                arguments=arguments,
                risk=manifest.risk,
                permission=permission,
                result={"success": result.success, "message": result.message, "data": result.data},
                duration_ms=0,
                verification="not_executed",
            )
