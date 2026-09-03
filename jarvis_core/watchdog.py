from __future__ import annotations
import threading
import time
import fnmatch
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .health import HealthManager, HealthStatus
from .logging import redact


@dataclass(slots=True)
class Probe:
    check: Callable[[], bool]
    interval: float
    next_run: float = 0.0
    recover: Callable[[], bool] | None = None
    failure_threshold: int = 3
    failures: int = 0
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3


class Watchdog:
    def __init__(self, health: HealthManager, tick_seconds: float = 0.25):
        self._health, self._tick = health, tick_seconds
        self._probes: dict[str, Probe] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(
        self,
        component: str,
        check: Callable[[], bool],
        interval: float = 5.0,
        *,
        recover=None,
        failure_threshold=3,
        max_recovery_attempts=3,
    ) -> None:
        self._probes[component] = Probe(
            check,
            max(0.1, interval),
            recover=recover,
            failure_threshold=max(1, int(failure_threshold)),
            max_recovery_attempts=max(0, int(max_recovery_attempts)),
        )

    def check_now(self, component: str) -> bool:
        try:
            probe = self._probes[component]
            healthy = bool(probe.check())
            if healthy:
                probe.failures = 0
                probe.recovery_attempts = 0
                self._health.report(component, HealthStatus.HEALTHY)
                return True
            probe.failures += 1
            if (
                probe.recover
                and probe.failures >= probe.failure_threshold
                and probe.recovery_attempts < probe.max_recovery_attempts
            ):
                probe.recovery_attempts += 1
                recovered = bool(probe.recover())
                self._health.report(
                    component,
                    HealthStatus.DEGRADED,
                    f"recovery attempt {probe.recovery_attempts}: {'accepted' if recovered else 'failed'}",
                )
                return False
            self._health.report(component, HealthStatus.FAILED, f"consecutive failures: {probe.failures}")
            return False
        except Exception as exc:
            self._health.report(component, HealthStatus.FAILED, redact(f"{type(exc).__name__}: {exc}"))
            return False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="jarvis-watchdog", daemon=True)
        self._thread = thread
        thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._tick):
            now = time.monotonic()
            for name, probe in tuple(self._probes.items()):
                if now >= probe.next_run:
                    self.check_now(name)
                    probe.next_run = now + probe.interval

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


@dataclass(slots=True)
class FilesystemWatcher:
    watch_id: str
    path: str
    events: tuple[str, ...]
    recursive: bool
    started_at: str
    status: str
    observer: object
    debounce_ms: int
    filters: tuple[str, ...]
    last_events: dict[tuple[str, str, str], float]


class FilesystemWatchRegistry:
    """In-process, owned filesystem watchers backed by the shared EventBus."""

    VALID_EVENTS = frozenset({"created", "modified", "deleted", "moved"})
    DEFAULT_FILTERS = ("~$*", "*.tmp", "*.swp", "*.swo")

    def __init__(self, event_bus, notifications=None, logger=None):
        self.events = event_bus
        self.notifications = notifications
        self.logger = logger
        self._watchers: dict[str, FilesystemWatcher] = {}
        self._lock = threading.RLock()
        self._closed = False

    @staticmethod
    def _path(value: str) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(str(value or "")))).resolve()

    @classmethod
    def _ignored(cls, path: str, filters: tuple[str, ...]) -> bool:
        name = Path(path).name
        return any(fnmatch.fnmatch(name, pattern) for pattern in filters)

    def start(self, path: str, events=None, recursive: bool = False, debounce_ms: int = 750, filters=None) -> dict:
        with self._lock:
            self._closed = False
        target = self._path(path)
        if not target.exists() or not target.is_dir():
            return {"success": False, "message": "La cartella indicata non esiste o non è una directory.", "data": {"path": str(target)}}
        if not os.access(target, os.R_OK):
            return {"success": False, "message": "La cartella indicata non è accessibile in lettura.", "data": {"path": str(target)}}
        selected = tuple(dict.fromkeys(str(item).casefold().strip() for item in (events or self.VALID_EVENTS) if str(item).casefold().strip()))
        if not selected or not set(selected) <= self.VALID_EVENTS:
            return {"success": False, "message": "Eventi Watchdog non validi.", "data": {"allowed": sorted(self.VALID_EVENTS)}}
        debounce = max(0, min(10000, int(debounce_ms)))
        patterns = tuple(str(item) for item in (filters or self.DEFAULT_FILTERS) if str(item).strip())
        key = (str(target).casefold(), selected, bool(recursive))
        with self._lock:
            for watcher in self._watchers.values():
                if (watcher.path.casefold(), watcher.events, watcher.recursive) == key and watcher.status == "running":
                    return {"success": True, "message": "Questa cartella è già monitorata.", "data": self._row(watcher) | {"duplicate": True}}
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return {"success": False, "message": "La libreria Watchdog non è disponibile.", "data": {}}

        watch_id = "watch-" + uuid.uuid4().hex[:12]
        registry = self

        class Handler(FileSystemEventHandler):
            def _emit(self, event_type, event):
                if event_type not in selected or bool(getattr(event, "is_directory", False)):
                    return
                source = str(getattr(event, "src_path", ""))
                destination = str(getattr(event, "dest_path", "")) if event_type == "moved" else ""
                if registry._ignored(source, patterns) or (destination and registry._ignored(destination, patterns)):
                    return
                registry._emit(watch_id, event_type, source, destination, debounce)

            def on_created(self, event): self._emit("created", event)
            def on_modified(self, event): self._emit("modified", event)
            def on_deleted(self, event): self._emit("deleted", event)
            def on_moved(self, event): self._emit("moved", event)

        observer = Observer()
        try:
            observer.daemon = True
            observer.schedule(Handler(), str(target), recursive=bool(recursive))
            observer.start()
        except Exception as exc:
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception:
                pass
            return {"success": False, "message": redact(f"Avvio Watchdog fallito: {exc}"), "data": {}}
        watcher = FilesystemWatcher(watch_id, str(target), selected, bool(recursive), time.strftime("%Y-%m-%dT%H:%M:%S%z"), "running", observer, debounce, patterns, {})
        with self._lock:
            if self._closed:
                observer.stop(); observer.join(timeout=2)
                return {"success": False, "message": "Watchdog in shutdown.", "data": {}}
            self._watchers[watch_id] = watcher
        self.events.publish("watchdog.started", self._row(watcher), source="watchdog")
        return {"success": True, "message": f"Monitoraggio avviato per {target}.", "data": self._row(watcher)}

    def _emit(self, watch_id: str, event_type: str, path: str, destination: str, debounce_ms: int) -> None:
        now = time.monotonic()
        with self._lock:
            watcher = self._watchers.get(watch_id)
            if watcher is None or watcher.status != "running":
                return
            key = (event_type, path.casefold(), destination.casefold())
            if now - watcher.last_events.get(key, -float("inf")) < debounce_ms / 1000:
                return
            watcher.last_events[key] = now
            payload = {"type": event_type, "path": path, "destination": destination, "watch_id": watch_id, "directory": False}
        self.events.publish("watchdog.filesystem", payload, source="watchdog", deduplication_key=f"{watch_id}:{event_type}:{path}:{destination}")
        if self.notifications is not None:
            verb = {"created": "creato", "modified": "modificato", "deleted": "eliminato", "moved": "spostato"}[event_type]
            self.notifications.notify("Watchdog", f"È stato {verb} {Path(destination or path).name} nella cartella monitorata.")

    @staticmethod
    def _row(watcher: FilesystemWatcher) -> dict:
        return {"watch_id": watcher.watch_id, "path": watcher.path, "events": list(watcher.events), "recursive": watcher.recursive, "started_at": watcher.started_at, "status": watcher.status}

    def list(self) -> list[dict]:
        with self._lock:
            return [self._row(item) for item in self._watchers.values() if item.status == "running"]

    def stop(self, watch_id: str | None = None, path: str | None = None) -> dict:
        target = str(self._path(path)).casefold() if path else None
        with self._lock:
            selected = [item for item in self._watchers.values() if (watch_id and item.watch_id == watch_id) or (target and item.path.casefold() == target)]
        if not selected:
            return {"success": False, "message": "Nessun monitoraggio corrispondente.", "data": {"watchers": self.list()}}
        for watcher in selected:
            self._stop_one(watcher)
        return {"success": True, "message": "Monitoraggio arrestato.", "data": {"stopped": [item.watch_id for item in selected]}}

    def stop_all(self) -> dict:
        with self._lock:
            selected = list(self._watchers.values())
        for watcher in selected:
            self._stop_one(watcher)
        return {"success": True, "message": f"Arrestati {len(selected)} monitoraggi.", "data": {"stopped": [item.watch_id for item in selected]}}

    def _stop_one(self, watcher: FilesystemWatcher) -> None:
        with self._lock:
            if watcher.status != "running":
                return
            watcher.status = "stopping"
        try:
            watcher.observer.stop()
            watcher.observer.join(timeout=3)
        finally:
            with self._lock:
                watcher.status = "stopped"
                self._watchers.pop(watcher.watch_id, None)
        self.events.publish("watchdog.stopped", self._row(watcher), source="watchdog")

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self.stop_all()
