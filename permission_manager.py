import hashlib
import hmac
import json
import os
import threading

from app_paths import data_path


STORE = data_path("jarvis_permissions.json")
DEFAULT = {
    "mode": "assisted",
    "categories": {
        "computer": "allow", "files_read": "allow", "files_write": "allow",
        "scripts": "confirm", "admin": "confirm", "install": "confirm",
        "external_send": "confirm", "destructive": "confirm", "forbidden": "deny",
    },
    "protected_paths": ["Windows", "Program Files", "Program Files (x86)"],
    "pin": None,
}
_SESSION_LOCK = threading.RLock()
_SESSION = None


def activate_session(name, role, permissions, method):
    global _SESSION
    with _SESSION_LOCK:
        _SESSION = {"name": str(name), "role": str(role).upper(), "permissions": dict(permissions or {}),
                    "method": str(method), "authenticated": True}
        return dict(_SESSION)


def clear_session():
    global _SESSION
    with _SESSION_LOCK:
        _SESSION = None


def session_profile():
    with _SESSION_LOCK:
        return dict(_SESSION) if _SESSION else None


def _load():
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
    except Exception:
        raw = {}
    result = json.loads(json.dumps(DEFAULT))
    result.update({k: v for k, v in raw.items() if k != "categories"})
    result["categories"].update({key: value for key, value in raw.get("categories", {}).items()
                                 if value in {"allow", "confirm", "deny"}})
    return result


def _save(data):
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def profile():
    data = _load()
    return {**data, "pin": bool(data.get("pin")), "confirmations": True, "session": session_profile()}


def set_mode(mode):
    mode = str(mode).lower().strip()
    if mode not in {"observe", "assisted", "autonomous"}:
        raise ValueError("Modalità non valida")
    data = _load(); data["mode"] = mode; _save(data)
    return mode


def set_category(category, decision):
    decision = str(decision).lower().strip()
    if decision not in {"allow", "confirm", "deny"}:
        raise ValueError("Permesso non valido")
    data = _load(); data["categories"][str(category)] = decision; _save(data)
    return decision


def decision(category):
    from jarvis_core.mode import RUNTIME_MODE
    if RUNTIME_MODE.safe and str(category) not in {"computer", "files_read"}:
        return "deny"
    data = _load()
    if data["mode"] == "observe":
        return "deny"
    session = session_profile()
    configured = (session.get("permissions", {}).get(str(category)) if session else None)
    if configured not in {"allow", "confirm", "deny"}:
        configured = data["categories"].get(str(category), "deny")
    if data["mode"] == "assisted" and configured == "allow" and str(category) in {"admin", "install", "destructive"}:
        return "confirm"
    return configured


def set_pin(pin):
    value = str(pin or "")
    if len(value) < 4:
        raise ValueError("Il PIN deve contenere almeno 4 caratteri")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, 200_000)
    data = _load(); data["pin"] = {"salt": salt.hex(), "digest": digest.hex(), "iterations": 200_000}; _save(data)
    return True


def verify_pin(pin):
    record = _load().get("pin")
    if not isinstance(record, dict) or not pin:
        return False
    try:
        digest = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), bytes.fromhex(record["salt"]), int(record["iterations"]))
        return hmac.compare_digest(digest.hex(), str(record["digest"]))
    except (KeyError, TypeError, ValueError):
        return False
