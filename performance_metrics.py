import atexit
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from app_paths import data_path


STORE = data_path("jarvis_metrics.json")
_LOCK = threading.RLock()
_DATA = None
_DIRTY = False
_LAST_FLUSH = 0.0
_FLUSH_INTERVAL = 2.0
_SAMPLE_LIMIT = 512


def _load():
    global _DATA
    if _DATA is None:
        try:
            value = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
            _DATA = value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            _DATA = {}
    return _DATA


def _percentile(values, fraction):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))]


def _flush_locked(force=False):
    global _DIRTY, _LAST_FLUSH
    now = time.monotonic()
    if not _DIRTY or (not force and now - _LAST_FLUSH < _FLUSH_INTERVAL):
        return True
    data = _load(); data["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STORE); _DIRTY = False; _LAST_FLUSH = now
        return True
    except OSError:
        temporary.unlink(missing_ok=True)
        return False


def record_tool(tool, success, duration_ms):
    """O(1) hot-path recording; disk persistence is rate-limited and atomic."""
    global _DIRTY
    duration = max(0, int(duration_ms))
    with _LOCK:
        data = _load()
        row = data.setdefault(str(tool), {"calls": 0, "successes": 0, "failures": 0,
            "total_ms": 0, "average_ms": 0, "samples_ms": []})
        row["calls"] += 1; row["successes" if success else "failures"] += 1
        row["total_ms"] += duration; row["average_ms"] = int(row["total_ms"] / row["calls"])
        row["success_rate"] = round(row["successes"] / row["calls"], 3)
        samples = deque(row.get("samples_ms") or (), maxlen=_SAMPLE_LIMIT); samples.append(duration)
        row["samples_ms"] = list(samples)
        row["p50_ms"] = _percentile(samples, .50); row["p95_ms"] = _percentile(samples, .95)
        row["p99_ms"] = _percentile(samples, .99); row["max_ms"] = max(samples)
        _DIRTY = True
        return _flush_locked()


def flush():
    with _LOCK:
        return _flush_locked(force=True)


def report():
    with _LOCK:
        _flush_locked(force=True)
        data = json.loads(json.dumps(_load()))
    tools = {key: value for key, value in data.items() if isinstance(value, dict)}
    return {"successo": True, "messaggio": f"Metriche disponibili per {len(tools)} strumenti.", "dati": data}


atexit.register(flush)
