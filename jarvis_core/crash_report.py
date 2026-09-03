from __future__ import annotations

import json
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_path


def write_crash(exc_type, exc_value, exc_traceback, *, thread_name="main", path=None):
    target = Path(path) if path else data_path("logs") / "crash.jsonl"
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thread": str(thread_name),
        "exception_type": getattr(exc_type, "__name__", str(exc_type)),
        "message": str(exc_value),
        "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def install_crash_reporting(path=None):
    previous_sys = sys.excepthook
    previous_thread = threading.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        write_crash(exc_type, exc_value, exc_traceback, thread_name="main", path=path)
        previous_sys(exc_type, exc_value, exc_traceback)

    def thread_hook(args):
        write_crash(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            thread_name=getattr(args.thread, "name", "thread"),
            path=path,
        )
        previous_thread(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    return {"sys": previous_sys, "thread": previous_thread}
