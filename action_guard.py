import hashlib
import json
import threading
import time
from permission_manager import decision
from permission_engine import PermissionEngine, RiskClassifier


_LOCK = threading.RLock()
_PENDING = {}

_CLASSIFIER = RiskClassifier()
_ENGINE = PermissionEngine()
# Compatibility exports for simulation/reporting code. Enforcement is owned by
# the typed classifier above, so these sets cannot weaken policy decisions.
HIGH_RISK = {name for name, policy in _CLASSIFIER._POLICIES.items()
             if policy.risk.value in {"admin", "destructive", "forbidden"}}
CONFIRM_RISK = {name for name, policy in _CLASSIFIER._POLICIES.items()
                if policy.risk.value == "sensitive"}


def risk_level(tool_name):
    policy = _CLASSIFIER.classify(tool_name)
    verdict = _ENGINE.evaluate(policy, decision(policy.category))
    if verdict == "deny":
        return "denied"
    return "safe" if verdict == "allow" else policy.risk.value


def stage(tool_name, arguments, *, risk=None):
    original_arguments = dict(arguments or {})
    payload = json.dumps([tool_name, original_arguments], ensure_ascii=False, sort_keys=True)
    created = time.time()
    action_id = hashlib.sha256(f"{created}:{payload}".encode()).hexdigest()[:8]
    with _LOCK:
        _PENDING[action_id] = {
            "action_id": action_id,
            "tool": str(tool_name),
            "skill": str(original_arguments.get("skill") or "") or None,
            "arguments": original_arguments,
            "risk": str(risk or "") or None,
            "created": created,
            "timestamp": created,
            "state": "pending_confirmation",
        }
    return action_id


def take(action_id, max_age=300):
    with _LOCK:
        action = _PENDING.pop(str(action_id).lower(), None)
    if not action or time.time() - action["created"] > max_age:
        return None
    return dict(action)


def cancel(action_id, max_age=300):
    """Consume one pending action without executing it."""
    with _LOCK:
        action = _PENDING.pop(str(action_id).lower(), None)
    if not action or time.time() - action["created"] > max_age:
        return None
    return dict(action)


def _purge_expired_locked(max_age):
    cutoff = time.time() - max(0.0, float(max_age))
    for action_id, action in list(_PENDING.items()):
        if action.get("created", 0) < cutoff:
            _PENDING.pop(action_id, None)


def pending(max_age=300):
    with _LOCK:
        _purge_expired_locked(max_age)
        return {key: dict(value) for key, value in _PENDING.items()}


def latest(max_age=300):
    """Restituisce l'ID dell'azione in attesa più recente, senza consumarla."""
    valid = list(pending(max_age).items())
    if not valid:
        return None
    return max(valid, key=lambda item: item[1]["created"])[0]
