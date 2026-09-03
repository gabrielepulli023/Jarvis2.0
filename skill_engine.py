import json
import re
import threading

from app_paths import data_path


STORE = data_path("jarvis_skills.json")
_LOCK = threading.RLock()


def _load():
    if not STORE.exists():
        return {}
    try:
        value = json.loads(STORE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(value):
    STORE.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_name(name):
    return re.sub(r"[^a-z0-9à-ÿ_-]+", " ", str(name).lower()).strip()


def create_skill(name, commands):
    key = normalize_name(name)
    steps = [str(x).strip() for x in commands if str(x).strip()]
    if not key or not steps:
        raise ValueError("Nome o comandi mancanti")
    with _LOCK:
        skills = _load()
        skills[key] = {"name": str(name).strip(), "commands": steps}
        _save(skills)
    return skills[key]


def get_skill(name):
    with _LOCK:
        return _load().get(normalize_name(name))


def list_skills():
    with _LOCK:
        return list(_load().values())


def delete_skill(name):
    with _LOCK:
        skills = _load()
        removed = skills.pop(normalize_name(name), None)
        if removed:
            _save(skills)
        return bool(removed)
