import json
import logging
import os
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QThread, Signal

from app_paths import data_path
from jarvis_core.logging import redact


STORE = data_path("jarvis_event_rules.json")
LOGGER = logging.getLogger(__name__)


def _load():
    try:
        value = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(value):
    temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STORE)


def add_rule(trigger_type, trigger_value, command):
    trigger_type = str(trigger_type).lower().strip()
    if trigger_type not in {"file_created", "process_started", "cpu_above", "disk_above"}:
        raise ValueError("Tipo evento non supportato")
    command = str(command or "").strip()
    if not command:
        raise ValueError("Il comando della regola non può essere vuoto")
    item = {"id": f"e{int(time.time() * 1000)}", "type": trigger_type, "value": str(trigger_value), "command": command, "enabled": True, "last_run": None}
    data = _load(); data.append(item); _save(data)
    return item


def list_rules():
    return _load()


def set_rule_enabled(rule_id, enabled):
    data = _load(); found = False
    for item in data:
        if item.get("id") == rule_id: item["enabled"] = bool(enabled); found = True
    if found: _save(data)
    return found


def delete_rule(rule_id):
    data = _load(); remaining = [x for x in data if x.get("id") != rule_id]
    if len(remaining) == len(data): return False
    _save(remaining); return True


class EventAutomationWorker(QThread):
    command = Signal(str)
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._files = {}
        self._processes = set()

    def stop(self): self._running = False

    def _fire(self, item, key, cooldown=60):
        now = time.time()
        if now - float(item.get("last_run") or 0) < cooldown: return
        item["last_run"] = now
        self.notice.emit(f"Regola {item['id']} attivata")
        self.command.emit(item["command"])

    def _check(self):
        rules = _load(); changed = False
        processes = {str(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
        for item in rules:
            if not item.get("enabled"): continue
            try:
                kind, value = item.get("type"), str(item.get("value", ""))
                before = item.get("last_run")
                if kind == "process_started" and value.lower() in processes and value.lower() not in self._processes:
                    self._fire(item, value)
                elif kind == "cpu_above" and psutil.cpu_percent(interval=None) >= float(value):
                    self._fire(item, value, 300)
                elif kind == "disk_above" and psutil.disk_usage("C:\\").percent >= float(value):
                    self._fire(item, value, 900)
                elif kind == "file_created":
                    folder = Path(value).expanduser()
                    current = {str(p) for p in folder.iterdir()} if folder.is_dir() else set()
                    previous = self._files.setdefault(value, current)
                    if current - previous: self._fire(item, value, 2)
                    self._files[value] = current
                changed = changed or before != item.get("last_run")
            except (OSError, ValueError, TypeError, KeyError, psutil.Error) as exc:
                LOGGER.warning("event automation rule %s skipped: %s", item.get("id", "unknown"), exc)
                self.notice.emit(redact(f"Regola automazione ignorata: {exc}"))
        self._processes = processes
        if changed: _save(rules)

    def run(self):
        while self._running:
            try:
                self._check()
            except (OSError, ValueError, TypeError, psutil.Error) as exc:
                LOGGER.warning("event automation check failed: %s", exc)
                self.notice.emit(redact(f"Controllo automazioni non riuscito: {exc}"))
            for _ in range(10):
                if not self._running: return
                self.msleep(500)
