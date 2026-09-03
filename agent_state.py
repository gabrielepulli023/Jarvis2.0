import json
import os
import threading
import time
from datetime import datetime

from app_paths import data_path
from mission_control import build_plan, completion_gate, verify_result
from adaptive_learning import learn_completed_mission


STORE = data_path("jarvis_agent_jobs.json")
_LOCK = threading.RLock()


def _load():
    try:
        value = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(value):
    temporary = STORE.with_suffix(STORE.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value[-100:], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STORE)


def begin(request, plan=None):
    item = {
        "id": f"j{int(time.time() * 1000)}", "request": str(request),
        "status": "running", "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None, "plan": plan or {"goal": str(request), "steps": build_plan(request), "source": "local"}, "steps": [],
        "checkpoint": {"completed_steps": 0, "last_tool": None}, "resumable": True,
    }
    with _LOCK:
        jobs = _load(); jobs.append(item); _save(jobs)
    return item["id"]


def add_step(job_id, tool, arguments, result):
    with _LOCK:
        jobs = _load()
        for job in jobs:
            if job.get("id") == job_id:
                verification = verify_result(tool, arguments, result)
                job["steps"].append({"tool": tool, "arguments": arguments, "success": bool(result.get("successo")), "message": str(result.get("messaggio", ""))[:1000], "verification": verification, "at": datetime.now().isoformat(timespec="seconds")})
                job["checkpoint"] = {"completed_steps": len(job["steps"]), "last_tool": tool, "last_success": bool(result.get("successo"))}
                _save(jobs); return True
    return False


def finish(job_id, status, summary=""):
    with _LOCK:
        jobs = _load()
        for job in jobs:
            if job.get("id") == job_id:
                final_status = str(status)
                gate_message = ""
                if final_status == "completed":
                    final_status, gate_message = completion_gate(job.get("steps", []))
                job["status"] = final_status
                job["verification_summary"] = gate_message
                job["summary"] = str(summary)
                job["resumable"] = final_status not in {"completed"}
                job["finished_at"] = datetime.now().isoformat(timespec="seconds")
                _save(jobs)
                if final_status == "completed":
                    learn_completed_mission(job)
                return final_status
    return False


def recent(limit=10):
    with _LOCK:
        return list(reversed(_load()))[:max(1, min(int(limit), 50))]


def latest_resumable():
    with _LOCK:
        for job in reversed(_load()):
            if job.get("resumable") or job.get("status") in {"paused", "partial", "needs_attention", "needs_verification", "limit_reached"}:
                return job
    return None


def get_job(job_id):
    with _LOCK:
        return next((job for job in _load() if job.get("id") == job_id), None)


def add_review(job_id, review):
    with _LOCK:
        jobs = _load()
        for job in jobs:
            if job.get("id") == job_id:
                job.setdefault("reviews", []).append({**dict(review or {}), "at": datetime.now().isoformat(timespec="seconds")})
                _save(jobs)
                return True
    return False


def recover_interrupted():
    with _LOCK:
        jobs = _load(); count = 0
        for job in jobs:
            if job.get("status") == "running":
                job["status"] = "paused"; job["resumable"] = True
                job["resume_hint"] = "Riprendi dall'ultimo checkpoint verificato"
                job["finished_at"] = datetime.now().isoformat(timespec="seconds"); count += 1
        if count: _save(jobs)
    return count
