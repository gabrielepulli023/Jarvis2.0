from __future__ import annotations
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Sequence
import psutil
from .events import EventBus


@dataclass(slots=True)
class ManagedProcess:
    id: str
    mission_id: str | None
    command: tuple[str, ...]
    process: subprocess.Popen
    started_at: float
    launch_options: dict[str, Any]


class ProcessManager:
    def __init__(self, events: EventBus):
        self._events = events
        self._items: dict[str, ManagedProcess] = {}
        self._lock = threading.RLock()

    def start(self, command: Sequence[str], *, mission_id: str | None = None, **kwargs) -> ManagedProcess:
        if isinstance(command, (str, bytes)):
            raise TypeError("command must be an argument sequence")
        process = subprocess.Popen(tuple(command), shell=False, **kwargs)
        item = ManagedProcess(uuid.uuid4().hex[:12], mission_id, tuple(command), process, time.time(), dict(kwargs))
        with self._lock:
            self._items[item.id] = item
        self._events.publish("process.started", {"id": item.id, "pid": process.pid, "mission_id": mission_id})
        threading.Thread(target=self._observe_exit, args=(item,), name=f"jarvis-process-{item.id}", daemon=True).start()
        return item

    def _observe_exit(self, item: ManagedProcess) -> None:
        returncode = item.process.wait()
        self._events.publish(
            "process.exited",
            {"id": item.id, "pid": item.process.pid, "mission_id": item.mission_id, "returncode": returncode},
        )

    def snapshot(self) -> list[dict]:
        with self._lock:
            items = tuple(self._items.values())
        return [
            {
                "id": x.id,
                "pid": x.process.pid,
                "mission_id": x.mission_id,
                "command": x.command,
                "started_at": x.started_at,
                "running": x.process.poll() is None,
                "returncode": x.process.poll(),
            }
            for x in items
        ]

    def inventory(self, limit: int = 500) -> list[dict]:
        """Read-only OS process inventory; inaccessible fields degrade to None."""
        rows: list[dict[str, Any]] = []
        for process in psutil.process_iter(("pid", "ppid", "name", "exe", "status", "username", "create_time")):
            if len(rows) >= max(1, min(int(limit), 5000)):
                break
            try:
                info = dict(process.info)
                memory = process.memory_info().rss
                cpu = process.cpu_percent(None)
                children = [child.pid for child in process.children(recursive=False)]
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                info = {
                    "pid": process.pid,
                    "ppid": None,
                    "name": None,
                    "exe": None,
                    "status": "inaccessible",
                    "username": None,
                    "create_time": None,
                }
                memory = None
                cpu = None
                children = []
            rows.append({**info, "cpu_percent": cpu, "memory_bytes": memory, "children": children})
        return rows

    def terminate(self, process_id: str, timeout: float = 3.0) -> bool:
        with self._lock:
            item = self._items.get(process_id)
        if not item or item.process.poll() is not None:
            return False
        item.process.terminate()
        try:
            item.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            item.process.kill()
            item.process.wait(timeout=timeout)
        self._events.publish("process.stopped", {"id": item.id, "returncode": item.process.returncode})
        return True

    def force_terminate(self, process_id: str, timeout: float = 3.0) -> bool:
        with self._lock:
            item = self._items.get(str(process_id))
        if not item or item.process.poll() is not None:
            return False
        item.process.kill()
        item.process.wait(timeout=max(0.1, float(timeout)))
        self._events.publish(
            "process.killed", {"id": item.id, "pid": item.process.pid, "returncode": item.process.returncode}
        )
        return True

    def kill_tree(self, process_id: str, timeout: float = 3.0) -> int:
        """Kill only a tree rooted in a process launched and tracked by JARVIS."""
        with self._lock:
            item = self._items.get(str(process_id))
        if not item or item.process.poll() is not None:
            return 0
        try:
            root = psutil.Process(item.process.pid)
            children = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            children = []
        count = 0
        for child in reversed(children):
            try:
                child.kill()
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if self.force_terminate(item.id, timeout):
            count += 1
        self._events.publish("process.tree_killed", {"id": item.id, "count": count})
        return count

    def restart(self, process_id: str, timeout: float = 3.0) -> ManagedProcess | None:
        with self._lock:
            item = self._items.get(str(process_id))
        if item is None:
            return None
        if item.process.poll() is None and not self.terminate(item.id, timeout):
            return None
        restarted = self.start(item.command, mission_id=item.mission_id, **item.launch_options)
        self._events.publish(
            "process.restarted", {"previous_id": item.id, "id": restarted.id, "pid": restarted.process.pid}
        )
        return restarted

    def shutdown(self) -> None:
        for row in self.snapshot():
            if row["running"]:
                self.terminate(row["id"])

    def terminate_all(self) -> int:
        return sum(self.terminate(row["id"]) for row in self.snapshot() if row["running"])
