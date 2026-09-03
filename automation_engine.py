import json
import threading
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from app_paths import data_path


STORE = data_path("jarvis_routines.json")
_LOCK = threading.RLock()


def _load():
    if not STORE.exists():
        return []
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STORE.parent, delete=False) as handle:
        handle.write(json.dumps(items, ensure_ascii=False, indent=2))
        temporary = Path(handle.name)
    temporary.replace(STORE)


def _command(command):
    value = str(command or "").strip()
    if not value:
        raise ValueError("routine command cannot be empty")
    return value


def add_daily(time_hhmm, command):
    datetime.strptime(time_hhmm, "%H:%M")
    routine = {
        "id": f"r{uuid.uuid4().hex}", "type": "daily", "time": time_hhmm,
        "command": _command(command), "enabled": True, "last_run": None,
    }
    with _LOCK:
        items = _load(); items.append(routine); _save(items)
    return routine


def add_once(run_at, command):
    if isinstance(run_at, str):
        run_at = datetime.fromisoformat(run_at)
    routine = {
        "id": f"r{uuid.uuid4().hex}", "type": "once",
        "run_at": run_at.isoformat(timespec="minutes"), "command": _command(command),
        "enabled": True, "last_run": None,
    }
    with _LOCK:
        items = _load(); items.append(routine); _save(items)
    return routine


def add_after(minutes, command):
    minutes = int(minutes)
    if minutes <= 0:
        raise ValueError("minutes must be greater than zero")
    return add_once(datetime.now() + timedelta(minutes=minutes), command)


def list_routines():
    with _LOCK:
        return list(_load())


def set_enabled(routine_id, enabled):
    with _LOCK:
        items = _load()
        found = False
        for item in items:
            if item.get("id") == routine_id:
                item["enabled"] = bool(enabled); found = True
        _save(items)
    return found


def delete_routine(routine_id):
    with _LOCK:
        items = _load()
        remaining = [item for item in items if item.get("id") != routine_id]
        if len(remaining) == len(items):
            return False
        _save(remaining)
        return True


def due(now=None):
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")
    ready = []
    with _LOCK:
        items = _load()
        for item in items:
            is_daily_due = item.get("type") == "daily" and item.get("time") == hhmm and item.get("last_run") != today
            is_once_due = item.get("type") == "once" and item.get("run_at", "") <= now.isoformat(timespec="minutes") and not item.get("last_run")
            if item.get("enabled") and (is_daily_due or is_once_due):
                item["last_run"] = today
                if item.get("type") == "once":
                    item["enabled"] = False
                ready.append(dict(item))
        if ready:
            _save(items)
    return ready
