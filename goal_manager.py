import json
import threading
from datetime import datetime
from app_paths import data_path


STORE = data_path("jarvis_goals.json")
_LOCK = threading.RLock()


def _load():
    if not STORE.exists():
        return []
    try:
        value = json.loads(STORE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(items):
    STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def create_goal(title, steps=None):
    title = str(title or "").strip()
    if not title:
        raise ValueError("Titolo obiettivo mancante")
    now = datetime.now().isoformat(timespec="seconds")
    item = {
        "id": f"g{int(datetime.now().timestamp())}",
        "title": title,
        "status": "active",
        "created_at": now,
        "steps": [
            {"text": str(step).strip(), "done": False}
            for step in (steps or []) if str(step).strip()
        ],
    }
    with _LOCK:
        items = _load(); items.append(item); _save(items)
    return item


def list_goals(active_only=False):
    with _LOCK:
        items = list(_load())
    return [x for x in items if x.get("status") == "active"] if active_only else items


def add_step(goal_id, text):
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == goal_id:
                item.setdefault("steps", []).append({"text": str(text).strip(), "done": False})
                _save(items)
                return item
    return None


def complete_step(goal_id, number):
    index = int(number) - 1
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == goal_id and 0 <= index < len(item.get("steps", [])):
                item["steps"][index]["done"] = True
                if item["steps"] and all(step.get("done") for step in item["steps"]):
                    item["status"] = "completed"
                _save(items)
                return item
    return None


def close_goal(goal_id):
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == goal_id:
                item["status"] = "completed"
                _save(items)
                return item
    return None
