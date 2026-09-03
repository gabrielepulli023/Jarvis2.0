import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app_paths import data_path
from jarvis_core.logging import redact


STORE = data_path("jarvis_async_tasks.json")


class AsyncEngine:
    def __init__(self):
        self._executors = {
            "ai": ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-ai"),
            "vision": ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-vision"),
            "automation": ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-automation"),
            "io": ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-io"),
            "voice": ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-voice"),
        }
        self._lock = threading.RLock()
        self._tasks = {}
        self._history = []
        self._shutting_down = threading.Event()

    def submit(self, lane, function, *args, priority=5, timeout=None, label=None, **kwargs):
        if self._shutting_down.is_set():
            raise RuntimeError("JARVIS shutdown in progress; new task rejected")
        lane = lane if lane in self._executors else "io"
        task_id = uuid.uuid4().hex[:12]
        created = time.time()

        def run():
            with self._lock:
                row = self._tasks.get(task_id)
                if row:
                    row.update(status="running", started_at=time.time())
            return function(*args, **kwargs)

        record = {
            "id": task_id, "lane": lane, "label": str(label or getattr(function, "__name__", "task")),
            "priority": int(priority), "timeout": timeout, "status": "queued",
            "created_at": created, "future": None,
        }
        with self._lock:
            self._tasks[task_id] = record
        future = self._executors[lane].submit(run)
        with self._lock:
            record["future"] = future

        def completed(done):
            finished = time.time()
            with self._lock:
                row = self._tasks.pop(task_id, record)
                if done.cancelled():
                    status, error = "cancelled", None
                else:
                    error = redact(repr(done.exception())) if done.exception() else None
                    status = "failed" if error else "completed"
                history = {key: value for key, value in row.items() if key != "future"}
                history.update(status=status, error=error, finished_at=finished, duration_ms=int((finished - row.get("started_at", created)) * 1000))
                self._history.append(history)
                self._history = self._history[-300:]
                self._save()

        future.add_done_callback(completed)
        return task_id, future

    def cancel(self, task_id):
        with self._lock:
            row = self._tasks.get(str(task_id))
        return bool(row and row.get("future") and row["future"].cancel())

    def cancel_all(self):
        with self._lock:
            futures = [row.get("future") for row in self._tasks.values() if row.get("future")]
        return sum(bool(future.cancel()) for future in futures)

    def snapshot(self):
        with self._lock:
            active = [{key: value for key, value in row.items() if key != "future"} for row in self._tasks.values()]
            history = list(self._history[-50:])
        return {"active": active, "history": history, "lanes": list(self._executors)}

    def _save(self):
        try:
            STORE.write_text(json.dumps(self._history, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def shutdown(self):
        self._shutting_down.set()
        with self._lock:
            for row in self._tasks.values():
                if row.get("future"):
                    row["future"].cancel()
        for executor in self._executors.values():
            executor.shutdown(wait=False, cancel_futures=True)

    @property
    def shutting_down(self):
        return self._shutting_down.is_set()


ENGINE = AsyncEngine()


def report():
    data = ENGINE.snapshot()
    return {"successo": True, "messaggio": f"Attività asincrone attive: {len(data['active'])}.", "dati": data}
