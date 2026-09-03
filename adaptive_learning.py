import hashlib
import json
import threading
import os
from datetime import datetime, timezone

from app_paths import data_path


STORE = data_path("jarvis_learned_procedures.json")
_LOCK = threading.RLock()
SENSITIVE_KEYS = {"password", "pin", "otp", "token", "secret", "api_key", "card", "cvv"}


def _safe_arguments(arguments):
    return {
        str(key): ("<redacted>" if str(key).lower() in SENSITIVE_KEYS else str(value)[:300])
        for key, value in dict(arguments or {}).items()
    }


def learn_completed_mission(mission):
    if str(mission.get("status", "")).lower() not in {"completed", "complete"}:
        return None
    steps = [
        step for step in mission.get("steps", [])
        if step.get("success") and (step.get("verification") or {}).get("status") == "verified"
    ]
    if len(steps) < 2:
        return None
    sequence = [{"tool": step.get("tool"), "arguments": _safe_arguments(step.get("arguments"))} for step in steps]
    signature = hashlib.sha256("|".join(str(step["tool"]) for step in sequence).encode()).hexdigest()[:12]
    with _LOCK:
        try:
            data = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
        except Exception:
            data = {}
        row = data.setdefault(signature, {"signature": signature, "uses": 0, "sequence": sequence, "examples": []})
        row["uses"] += 1
        row["last_success"] = datetime.now(timezone.utc).isoformat()
        row["examples"] = (row.get("examples", []) + [str(mission.get("request", ""))[:500]])[-5:]
        row["ready_as_skill"] = row["uses"] >= 2
        temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
        try:
            STORE.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(STORE)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
    return row


def learned_report():
    with _LOCK:
        try:
            data = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
        except Exception:
            data = {}
    ready = [row for row in data.values() if row.get("ready_as_skill")]
    approved = [row for row in ready if row.get("approved") is True]
    return {"successo": True, "messaggio": f"Procedure osservate: {len(data)}; consolidate: {len(ready)}; approvate: {len(approved)}.", "dati": data}


def approve_procedure(signature: str, *, approved_by: str = "user"):
    """Approve a learned procedure explicitly; approval never executes it."""
    identity = str(signature or "").strip()
    with _LOCK:
        try:
            data = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
        except Exception:
            data = {}
        row = data.get(identity)
        if not row or not row.get("ready_as_skill"):
            return None
        row["approved"] = True
        row["approved_by"] = str(approved_by)[:80]
        row["approved_at"] = datetime.now(timezone.utc).isoformat()
        temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(STORE)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
        return dict(row)


def simulate_procedure(signature: str):
    """Return a redacted dry-run plan; execution is intentionally separate."""
    identity = str(signature or "").strip()
    with _LOCK:
        try:
            data = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
        except Exception:
            data = {}
    row = data.get(identity)
    if not row:
        return {"successo": False, "messaggio": "Procedura non trovata."}
    return {"successo": True, "messaggio": "Simulazione completata; nessuna azione eseguita.", "dati": {"signature": identity, "approved": bool(row.get("approved")), "steps": row.get("sequence", [])}}
