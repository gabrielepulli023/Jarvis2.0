import copy
import threading
import time


_LOCK = threading.RLock()
_CACHE = {}


def get(key):
    with _LOCK:
        row = _CACHE.get(str(key))
        if not row or row["expires"] <= time.time():
            _CACHE.pop(str(key), None)
            return None
        return copy.deepcopy(row["value"])


def put(key, value, ttl=2.0):
    with _LOCK:
        _CACHE[str(key)] = {"value": copy.deepcopy(value), "expires": time.time() + max(0.1, float(ttl))}
    return value


def clear():
    with _LOCK:
        count = len(_CACHE); _CACHE.clear()
    return count
