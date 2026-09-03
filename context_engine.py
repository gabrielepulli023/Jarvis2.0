import json
import os
import threading
from datetime import datetime

from app_paths import data_path


STORE = data_path("jarvis_context.json")
_LOCK = threading.RLock()


def _load():
    try:
        value = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def current():
    with _LOCK:
        return _load()


def update(request=None, result=None, window=None, tool=None):
    with _LOCK:
        data = _load()
        if request:
            data["last_request"] = str(request)[:2000]
        if result:
            data["last_result"] = str(result)[:3000]
        if window:
            data["active_window"] = str(window)[:500]
        if tool:
            data["last_tool"] = str(tool)[:100]
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, STORE)
        return data


def clear():
    with _LOCK:
        STORE.unlink(missing_ok=True)
    return True
