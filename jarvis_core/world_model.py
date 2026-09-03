"""Volatile, evidence-aware view of the currently observable world.

The model deliberately uses the canonical WorkingMemory as its only backing
store.  It is a context projection, not a planner or a persistent memory.
"""
from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from typing import Any, Mapping
from .reference_resolution import _verified


WORLD_PREFIX = "world.entities."
UI_TTL = 10.0
APP_TTL = 45.0
WINDOW_TTL = 20.0
ARTIFACT_TTL = 600.0
MISSION_TTL = 300.0
_SECRET = re.compile(r"(?i)(password|passphrase|api[_ -]?key|token|authorization|secret|cookie)\s*[:=]?\s*\S+")
_APP_KEYS = ("application", "app", "programma", "nome", "name")
_PATH_KEYS = ("path", "percorso", "output_path", "source_path", "file_path", "target")


def _safe(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "..."
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            if any(token in str(key).casefold() for token in ("password", "secret", "token", "api_key", "authorization", "cookie", "content")):
                continue
            output[str(key)] = _safe(item, depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_safe(item, depth + 1) for item in list(value)[:32]]
    if isinstance(value, str):
        return _SECRET.sub(r"\1: [REDACTED]", value)[:500]
    return value


def _find(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return str(candidate).strip()[:300]
        for child in value.values():
            found = _find(child, keys)
            if found:
                return found
    return None


class WorldModel:
    """Bounded property-level beliefs backed by ``memory.working``."""

    def __init__(self, working_memory, *, events=None, clock=time.monotonic):
        self.working = working_memory
        self.events = events
        self.clock = clock
        self._lock = threading.RLock()
        self.context = None
        self.perception = None

    @staticmethod
    def entity_id(entity_id: str, entity_type: str | None = None) -> str:
        value = str(entity_id or "unknown").strip().casefold().replace(" ", "_")
        return value if ":" in value else f"{str(entity_type or 'entity').casefold()}:{value}"

    @staticmethod
    def _app_token(value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/").casefold()
        leaf = text.rsplit("/", 1)[-1]
        if leaf.endswith(".exe"):
            leaf = leaf[:-4]
        return re.sub(r"[^a-z0-9]+", "_", leaf).strip("_")

    def application_identity(self, value: Any, aliases: list[Any] | tuple[Any, ...] = ()) -> str:
        candidates = [str(item).strip() for item in (value, *aliases) if str(item or "").strip()]
        tokens = [self._app_token(item) for item in candidates]
        existing = self.find("application", limit=128)
        for entity in existing:
            known = [str(entity.get("entity_id", "")).split(":", 1)[-1]]
            known.extend(entity.get("properties", {}).get("aliases", {}).get("value", []) or [])
            known_tokens = {self._app_token(item) for item in known}
            if known_tokens.intersection(tokens):
                return str(entity["entity_id"])
        executable_token = next((token for item, token in zip(candidates, tokens, strict=True) if item.lower().endswith(".exe") or "/" in item or "\\" in item), None)
        return f"application:{executable_token or next((token for token in tokens if token), 'unknown')}"

    def _key(self, entity_id: str, entity_type: str | None = None) -> str:
        if entity_type == "application" or str(entity_id).casefold().startswith("application:"):
            raw = str(entity_id).split(":", 1)[-1] if ":" in str(entity_id) else entity_id
            return WORLD_PREFIX + self.application_identity(raw)
        return WORLD_PREFIX + self.entity_id(entity_id, entity_type)

    def _load(self, entity_id: str, entity_type: str | None = None) -> dict[str, Any] | None:
        value = self.working.get(self._key(entity_id, entity_type))
        if not isinstance(value, dict):
            return None
        now = float(self.clock())
        value["properties"] = {
            name: belief for name, belief in value.get("properties", {}).items()
            if not isinstance(belief, Mapping) or belief.get("expires_at") is None or now < float(belief["expires_at"])
        }
        return value if value["properties"] or value.get("last_conflict") else None

    def observe(
        self,
        entity_id: str,
        properties: Mapping[str, Any] | None = None,
        *,
        entity_type: str | None = None,
        source: str = "unknown",
        confidence: float = 0.0,
        evidence_type: str = "inferred",
        ttl: float = APP_TTL,
    ) -> dict[str, Any]:
        """Merge property beliefs, applying deterministic evidence precedence."""
        if entity_type == "application" or str(entity_id).casefold().startswith("application:"):
            raw = str(entity_id).split(":", 1)[-1] if ":" in str(entity_id) else entity_id
            canonical = self.application_identity(raw)
        else:
            canonical = self.entity_id(entity_id, entity_type)
        kind = canonical.split(":", 1)[0]
        now = float(self.clock())
        confidence = max(0.0, min(1.0, float(confidence)))
        incoming_type = str(evidence_type)
        old = self._load(canonical) or {"entity_id": canonical, "entity_type": kind, "properties": {}}
        changed = False
        state_changed = False
        new_conflict = False
        conflicts = []
        rank = {"mentioned": 1, "intended": 2, "inferred": 3, "observed_perception": 5, "observed_structured": 6, "verified": 7}
        with self._lock:
            for name, raw in list(_safe(dict(properties or {})).items())[:32]:
                if name == "aliases" and isinstance(raw, list):
                    raw = raw[:16]
                if name == "focused" and raw is True and kind in {"application", "window"} and incoming_type == "observed_perception":
                    authoritative_focus = any(
                        isinstance(item.get("properties", {}).get("focused"), Mapping)
                        and item.get("properties", {}).get("focused", {}).get("value") is True
                        and item.get("properties", {}).get("focused", {}).get("source") in {"dom", "uia", "runtime_context", "process_snapshot"}
                        and float(item.get("properties", {}).get("focused", {}).get("confidence", 0)) >= confidence
                        for item in (self._load(key.removeprefix(WORLD_PREFIX)) or {} for key in self.working.namespace(WORLD_PREFIX))
                        if isinstance(item, Mapping) and item.get("entity_id") != canonical
                    )
                    if authoritative_focus:
                        conflicts.append({"property": name, "kept": "authoritative_focus", "rejected": raw})
                        continue
                existing = old["properties"].get(name)
                if isinstance(existing, Mapping):
                    expires = existing.get("expires_at")
                    if expires is not None and now >= float(expires):
                        existing = None
                if existing and existing.get("value") == raw:
                    existing_rank = rank.get(str(existing.get("evidence_type")), 0)
                    incoming_rank = rank.get(incoming_type, 0)
                    existing_confidence = float(existing.get("confidence", 0.0))
                    existing["updated_at"] = now
                    existing["expires_at"] = now + max(1.0, float(ttl))
                    if incoming_rank > existing_rank or confidence > existing_confidence:
                        existing["confidence"] = max(existing_confidence, confidence)
                        if incoming_rank >= existing_rank:
                            existing["source"] = str(source)[:120]
                            existing["evidence_type"] = incoming_type
                    changed = True
                    continue
                if existing and existing.get("value") != raw:
                    old_rank = rank.get(str(existing.get("evidence_type")), 0)
                    new_rank = rank.get(incoming_type, 0)
                    old_fresh = existing.get("expires_at") is None or now < float(existing["expires_at"])
                    if old_fresh and incoming_type == "inferred" and old_rank >= new_rank:
                        conflicts.append({"property": name, "kept": existing.get("value"), "rejected": raw})
                        continue
                    if old_fresh and incoming_type == "observed_perception" and existing.get("source") in {"process_snapshot", "runtime_context", "dom", "uia"} and float(existing.get("confidence", 0)) >= confidence:
                        conflicts.append({"property": name, "kept": existing.get("value"), "rejected": raw})
                        continue
                    if old_fresh and incoming_type not in {"observed_structured"} and new_rank < old_rank and confidence < float(existing.get("confidence", 0)):
                        conflicts.append({"property": name, "kept": existing.get("value"), "rejected": raw})
                        continue
                old["properties"][name] = {
                    "value": raw,
                    "confidence": confidence,
                    "source": str(source)[:120],
                    "evidence_type": incoming_type,
                    "updated_at": now,
                    "expires_at": now + max(1.0, float(ttl)),
                }
                changed = True
                state_changed = True
                if name == "focused" and raw is True and kind in {"application", "window"}:
                    self._clear_other_focus(canonical, now)
            if conflicts:
                conflict = {"entity_id": canonical, **conflicts[-1], "source": str(source)[:120]}
                if old.get("last_conflict") != conflict:
                    old["last_conflict"] = conflict
                    changed = True
                    new_conflict = True
            if changed:
                old["updated_at"] = now
                remaining = [float(item.get("expires_at")) - now for item in old["properties"].values() if isinstance(item, Mapping) and item.get("expires_at") is not None]
                self.working.set(self._key(canonical), old, ttl=max(1.0, max(remaining, default=1.0)), source=source, confidence=confidence)
                if self.events is not None and state_changed:
                    self.events.publish("world.updated", {"entity_id": canonical, "source": source}, source="world")
                if self.events is not None and new_conflict:
                    self.events.publish("world.conflict", {"entity_id": canonical, "conflict": conflicts[-1]}, source="world")
        return deepcopy(old)

    def _clear_other_focus(self, current_id: str, now: float) -> None:
        for key in tuple(self.working.namespace(WORLD_PREFIX)):
            entity = self._load(key.removeprefix(WORLD_PREFIX))
            if not isinstance(entity, dict) or entity.get("entity_id") == current_id:
                continue
            belief = entity.get("properties", {}).get("focused")
            if not isinstance(belief, Mapping) or belief.get("value") is not True:
                continue
            updated = deepcopy(entity)
            current = dict(belief)
            current.update({"value": False, "source": "focus_superseded", "evidence_type": "observed_structured", "updated_at": now})
            updated["properties"]["focused"] = current
            updated["updated_at"] = now
            remaining = [float(item.get("expires_at")) - now for item in updated["properties"].values() if isinstance(item, Mapping) and item.get("expires_at") is not None]
            self.working.set(key, updated, ttl=max(1.0, max(remaining, default=1.0)), source="focus_superseded", confidence=float(current.get("confidence", 0.98)))
            if self.events is not None:
                self.events.publish("world.updated", {"entity_id": updated.get("entity_id"), "source": "focus_superseded"}, source="world")

    def mention(self, entity_id: str, entity_type: str = "entity") -> dict[str, Any]:
        return self.observe(entity_id, {"mentioned": True}, entity_type=entity_type, source="conversation", confidence=0.5, evidence_type="mentioned", ttl=300)

    def observe_tool(self, tool: str, result: Mapping[str, Any] | None, arguments: Mapping[str, Any] | None = None) -> None:
        result = result if isinstance(result, Mapping) else {}
        args = arguments if isinstance(arguments, Mapping) else {}
        verified = _verified(result)
        name = _find(args, _APP_KEYS) or _find(result, _APP_KEYS)
        path = _find(result, _PATH_KEYS) or _find(args, _PATH_KEYS)
        tool_name = str(tool or "").casefold()
        executable = _find(args, ("executable", "exe")) or _find(result, ("executable", "exe"))
        if name and ("programma" in tool_name or tool_name.startswith("apps.") or "application" in tool_name):
            if verified:
                entity = self.application_identity(name, [executable] if executable else [])
                self.observe(entity, {"running": not ("chiudi" in tool_name or ".close" in tool_name), "focused": "focus" in tool_name, "aliases": [name, executable] if executable else [name]}, source="verified_tool", confidence=0.99, evidence_type="verified", ttl=APP_TTL)
        if path and verified and any(token in tool_name for token in ("file", "percorso", "convert", "crea", "scrivi", "write")):
            self.observe(f"artifact:{path}", {"path": path, "exists": True, "recent": True}, source="verified_tool", confidence=0.99, evidence_type="verified", ttl=ARTIFACT_TTL)

    def bind_context(self, context) -> None:
        self.context = context

    def bind_perception(self, perception) -> None:
        self.perception = perception

    def refresh(self, context_snapshot: Mapping[str, Any] | None = None) -> None:
        """Fuse already available runtime/perception snapshots; never observes actively."""
        snapshot = context_snapshot or {}
        opened_names = set()
        process_rows = snapshot.get("os_processes") if isinstance(snapshot.get("os_processes"), list) else []
        # Older callers supplied a complete list without metadata; preserve that
        # API while ContextEngine now explicitly marks truncated inventories.
        process_authoritative = bool(snapshot.get("os_processes_available")) and bool(snapshot.get("os_processes_complete", True))
        for row in process_rows:
            if isinstance(row, Mapping) and row.get("name"):
                opened_names.add(self._app_token(row.get("exe") or row.get("name")))
                entity = self.application_identity(row.get("exe") or row.get("name"), [row.get("name"), row.get("exe")])
                self.observe(entity, {"running": True, "pid": row.get("pid"), "aliases": [row.get("name"), row.get("exe")]}, source="process_snapshot", confidence=0.98, evidence_type="observed_structured", ttl=APP_TTL)
        for entity in self.find("application", limit=64):
            entity_name = str(entity.get("entity_id", "")).split(":", 1)[-1].casefold()
            running = entity.get("properties", {}).get("running", {}).get("value")
            if process_authoritative and running is True and entity_name not in opened_names:
                self.observe(entity["entity_id"], {"running": False}, source="process_snapshot", confidence=0.98, evidence_type="observed_structured", ttl=APP_TTL)
        active = snapshot.get("active_window")
        for row in snapshot.get("observed_applications", []) if isinstance(snapshot.get("observed_applications"), list) else []:
            if isinstance(row, Mapping) and (row.get("executable") or row.get("name")):
                entity = self.application_identity(row.get("executable") or row.get("name"), [row.get("name"), row.get("executable")])
                self.observe(entity, {"visible": True, "running": True, "aliases": [row.get("name"), row.get("executable")]}, source="window_snapshot", confidence=0.98, evidence_type="observed_structured", ttl=APP_TTL)
        if isinstance(active, Mapping) and (active.get("title") or active.get("executable")):
            title = str(active.get("title") or active.get("executable"))
            self.observe(f"window:{title}", {"title": title, "focused": True, "pid": active.get("pid")}, source="runtime_context", confidence=0.98, evidence_type="observed_structured", ttl=WINDOW_TTL)
            if active.get("executable"):
                entity = self.application_identity(active["executable"], [active.get("title")])
                self.observe(entity, {"focused": True, "running": True, "aliases": [active.get("title"), active.get("executable")]}, source="runtime_context", confidence=0.98, evidence_type="observed_structured", ttl=APP_TTL)
        current = None
        if self.perception is not None:
            try:
                current = self.perception.snapshot().get("current")
            except Exception:
                current = None
        if isinstance(current, Mapping):
            source = str(current.get("source") or "perception")
            evidence = "observed_perception"
            confidence = float(current.get("confidence", 0.0))
            application = current.get("application")
            if application and application != "unknown":
                self.observe(self.application_identity(application), {"visible": True, "focused": True}, source=source, confidence=confidence, evidence_type=evidence, ttl=APP_TTL)
            for element in list(current.get("elements") or [])[:20]:
                if isinstance(element, Mapping) and element.get("id"):
                    self.observe(f"ui:{element['id']}", {"name": element.get("name"), "role": element.get("role"), "state": element.get("state", {})}, source=source, confidence=float(element.get("confidence", confidence)), evidence_type=evidence, ttl=UI_TTL)
        missions = snapshot.get("current_task")
        if isinstance(missions, list) and missions:
            task = missions[0]
            if isinstance(task, Mapping) and task.get("id"):
                self.observe(f"task:{task['id']}", {key: task.get(key) for key in ("objective", "status", "updated_at")}, source="mission_store", confidence=0.98, evidence_type="observed_structured", ttl=MISSION_TTL)

    def get(self, entity_id: str) -> dict[str, Any] | None:
        entity = self._load(entity_id)
        return entity if entity and entity.get("properties") else None

    def find(self, entity_type: str | None = None, *, property_name: str | None = None, value: Any = None, limit: int = 32) -> list[dict[str, Any]]:
        rows = []
        now = float(self.clock())
        for _key, entity in self.working.namespace(WORLD_PREFIX).items():
            if isinstance(entity, Mapping):
                entity = deepcopy(entity)
                entity["properties"] = {
                    name: belief for name, belief in entity.get("properties", {}).items()
                    if not isinstance(belief, Mapping) or belief.get("expires_at") is None or now < float(belief["expires_at"])
                }
            if not isinstance(entity, Mapping):
                continue
            if entity_type and entity.get("entity_type") != entity_type:
                continue
            if property_name:
                belief = entity.get("properties", {}).get(property_name)
                if not isinstance(belief, Mapping) or (value is not None and belief.get("value") != value):
                    continue
            rows.append(deepcopy(entity))
        rows.sort(key=lambda row: float(row.get("updated_at", 0)), reverse=True)
        return rows[: max(1, min(100, int(limit)))]

    def snapshot(self, *, max_entities: int = 64) -> dict[str, Any]:
        rows = self.find(limit=max_entities)
        for row in rows:
            row["properties"] = dict(list(row.get("properties", {}).items())[:32])
        return {"entities": rows, "last_conflict": next((row.get("last_conflict") for row in rows if row.get("last_conflict")), None)}

    def explain(self, entity_id: str, property_name: str | None = None) -> dict[str, Any] | None:
        entity = self.get(entity_id)
        if not entity:
            return None
        if property_name:
            return deepcopy(entity.get("properties", {}).get(property_name))
        return entity

    def compact(self, max_chars: int = 1600) -> str:
        lines = []
        for entity in self.find(limit=32):
            facts = []
            for name, belief in list(entity.get("properties", {}).items())[:8]:
                if isinstance(belief, Mapping) and belief.get("value") not in (None, False):
                    facts.append(f"{name}={belief.get('value')}")
            if facts:
                lines.append(f"- {entity.get('entity_id')}: " + ", ".join(facts))
        limit = max(0, int(max_chars))
        prefix = "World state:\n"
        return (prefix + "\n".join(lines))[:limit]

    def clear(self) -> int:
        return self.working.clear_prefix(WORLD_PREFIX)

    def close(self) -> None:
        self.context = None
        self.perception = None
