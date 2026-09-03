import json
import os
import threading
from datetime import datetime, timezone
from app_paths import data_path
from jarvis_core.logging import redact


LOG_PATH = data_path("jarvis_audit.jsonl")
_LOCK = threading.RLock()


def record(event, **data):
    row = redact({"timestamp": datetime.now(timezone.utc).isoformat(), "event": str(event), **data})
    with _LOCK:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size>10_000_000:
            archive=LOG_PATH.with_suffix(".jsonl.1");archive.unlink(missing_ok=True);os.replace(LOG_PATH,archive)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row

def record_action(*,request_id,user_command,planner_decision,tool,arguments,risk,permission,result,duration_ms,verification):
    return record("action",request_id=str(request_id),user_command=str(user_command),planner_decision=planner_decision,
                  tool=str(tool),arguments=arguments,risk=str(risk),permission=str(permission),result=result,
                  duration_ms=max(0,int(duration_ms)),verification=verification)

def recent(limit=100):
    maximum=max(1,min(int(limit),1000))
    try:lines=LOG_PATH.read_text(encoding="utf-8",errors="replace").splitlines()[-maximum:]
    except OSError:return []
    rows=[]
    for line in lines:
        try:rows.append(json.loads(line))
        except json.JSONDecodeError:continue
    return rows
