from __future__ import annotations
import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


class ConfigManager:
    """Validated layered config: defaults, JSON file, then JARVIS_* environment."""

    def __init__(self, defaults: dict[str, Any] | None = None, path: Path | None = None):
        self._defaults, self._path, self._lock = deepcopy(defaults or {}), path, threading.RLock()
        self._values = self._load()

    def _load(self) -> dict[str, Any]:
        values = deepcopy(self._defaults)
        paths = [] if not self._path else (sorted(self._path.glob("*.json")) if self._path.is_dir() else [self._path])
        for path in paths:
            if not path.exists():
                continue
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                # A partially written optional layer must not prevent the core
                # runtime from starting with its defaults and other layers.
                continue
            if not isinstance(loaded, dict):
                raise ValueError("configuration root must be an object")
            self._merge(values, loaded)
        for key, current in tuple(values.items()):
            raw = os.environ.get(f"JARVIS_{key.upper()}")
            if raw is not None:
                values[key] = self._coerce(raw, current)
        return values

    @classmethod
    def _merge(cls, target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    @staticmethod
    def _coerce(raw: str, current: Any) -> Any:
        if isinstance(current, bool):
            normalized = raw.strip().lower()
            if normalized not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
                raise ValueError(f"invalid boolean: {raw}")
            return normalized in {"1", "true", "yes", "on"}
        if isinstance(current, int) and not isinstance(current, bool):
            return int(raw)
        if isinstance(current, float):
            return float(raw)
        return raw

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._values.get(key, default))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._values)
