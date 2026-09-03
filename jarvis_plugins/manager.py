from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis_skills import Capability, SkillRegistry, SkillResult

_RISK = {"safe": 0, "sensitive": 1, "admin": 2, "destructive": 3, "forbidden": 4}


@dataclass(frozen=True, slots=True)
class PluginTool:
    name: str
    skill: str
    permissions: frozenset[Capability]
    risk: str


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    permissions: frozenset[Capability]
    tools: tuple[PluginTool, ...]
    events: tuple[str, ...]

    @classmethod
    def load(cls, path: Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not data.get("name") or not data.get("version"):
            raise ValueError("Plugin name/version mancanti")
        permissions = frozenset(Capability(value) for value in data.get("permissions", []))
        tools = []
        for row in data.get("tools", []):
            if not row.get("name") or not row.get("skill"):
                raise ValueError("Tool plugin non valido")
            risk = str(row.get("risk", "safe"))
            if risk not in _RISK:
                raise ValueError("Rischio plugin non valido")
            tools.append(
                PluginTool(
                    str(row["name"]),
                    str(row["skill"]),
                    frozenset(Capability(value) for value in row.get("permissions", [])),
                    risk,
                )
            )
        events = tuple(str(value) for value in data.get("events", []) if str(value).strip())
        return cls(str(data["name"]), str(data["version"]), permissions, tuple(tools), events)


class PluginManager:
    """Declarative plugin layer; plugins may compose registered skills but cannot import code."""

    def __init__(self, skills: SkillRegistry, events, *, history_limit: int = 128):
        self.skills = skills
        self.events = events
        self._plugins: dict[str, PluginManifest] = {}
        self._unsubscribers: list[Callable[[], None]] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=max(16, int(history_limit)))
        self._lock = threading.RLock()

    def load_all(self, root: Path) -> list[str]:
        loaded = []
        for path in sorted(Path(root).glob("*/plugin.json")):
            self.load(path)
            loaded.append(path.parent.name)
        return loaded

    def load(self, path: Path) -> PluginManifest:
        manifest = PluginManifest.load(path)
        with self._lock:
            if manifest.name in self._plugins:
                raise ValueError(f"Plugin duplicato: {manifest.name}")
        for tool in manifest.tools:
            target = self.skills.manifest(tool.skill)
            if target is None:
                raise ValueError(f"Skill plugin inesistente: {tool.skill}")
            if not tool.permissions <= manifest.permissions:
                raise ValueError(f"Permessi tool fuori dal manifest: {tool.name}")
            if not target.permissions <= tool.permissions:
                raise ValueError(f"Permessi insufficienti per skill: {tool.skill}")
            if _RISK[tool.risk] < _RISK[target.risk]:
                raise ValueError(f"Il plugin riduce il rischio di {tool.skill}")
        with self._lock:
            self._plugins[manifest.name] = manifest
        for topic in manifest.events:
            self._unsubscribers.append(
                self.events.subscribe(topic, lambda event, name=manifest.name: self._remember(name, event))
            )
        return manifest

    def execute(self, plugin: str, tool: str, **arguments) -> SkillResult:
        with self._lock:
            manifest = self._plugins.get(str(plugin))
        if manifest is None:
            return SkillResult(False, f"Plugin non caricato: {plugin}")
        contribution = next((item for item in manifest.tools if item.name == tool), None)
        if contribution is None:
            return SkillResult(False, f"Tool plugin non trovato: {tool}")
        return self.skills.execute(contribution.skill, **arguments)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "plugins": [
                    {
                        "name": item.name,
                        "version": item.version,
                        "permissions": sorted(value.value for value in item.permissions),
                        "tools": [tool.name for tool in item.tools],
                        "events": list(item.events),
                    }
                    for item in self._plugins.values()
                ],
                "events": list(self._history),
            }

    def close(self):
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    def _remember(self, plugin, event):
        with self._lock:
            self._history.append(
                {"plugin": plugin, "topic": event.topic, "source": event.source, "timestamp": event.timestamp}
            )
