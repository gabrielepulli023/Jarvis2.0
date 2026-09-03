from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from jarvis_core.logging import redact

STALE_RUNNING_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class AutomationResult:
    automation_id: str
    status: str
    attempts: int
    outputs: tuple[dict, ...] = ()
    error: str = ""
    duplicate: bool = False


class AutomationEngine:
    """Persistent scheduler and event runner with idempotency and audit history."""

    def __init__(self, path: Path, dispatcher: Callable[[dict], dict] | None = None, sleeper=time.sleep):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dispatcher = dispatcher
        self._sleep = sleeper
        self._lock = threading.RLock()
        self._paused = threading.Event()
        self._event_queue: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=256)
        self._event_stop = threading.Event()
        self._event_thread: threading.Thread | None = None
        self._event_unsubscribe = None
        self._bound_events = None
        self._dropped_events = 0
        self._migrate()

    def bind(self, events):
        if self._event_unsubscribe:
            return
        self._bound_events = events

        def receive(event):
            if event.source == "automation" or event.topic.startswith("automation."):
                return
            payload = dict(event.payload or {})
            payload.setdefault("event_id", event.id)
            try:
                self._event_queue.put_nowait((event.topic, payload))
            except queue.Full:
                self._dropped_events += 1

        self._event_unsubscribe = events.subscribe("*", receive)
        self._event_stop.clear()
        thread = threading.Thread(target=self._event_loop, name="jarvis-automation-events", daemon=True)
        self._event_thread = thread
        thread.start()

    def _event_loop(self):
        while not self._event_stop.is_set():
            try:
                topic, payload = self._event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.handle_event(topic, payload)
            finally:
                self._event_queue.task_done()

    def close(self):
        if self._event_unsubscribe:
            self._event_unsubscribe()
            self._event_unsubscribe = None
        self._event_stop.set()
        if self._event_thread and self._event_thread is not threading.current_thread():
            self._event_thread.join(timeout=2)

    def healthy(self):
        return bool(self._event_thread and self._event_thread.is_alive())

    def restart_events(self):
        events = self._bound_events
        self.close()
        if events is None:
            return False
        self.bind(events)
        return self.healthy()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _migrate(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS automations(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,trigger_type TEXT NOT NULL,trigger_value TEXT NOT NULL,
                actions_json TEXT NOT NULL,enabled INTEGER NOT NULL,retries INTEGER NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS automation_runs(
                id TEXT PRIMARY KEY,automation_id TEXT NOT NULL,trigger_key TEXT NOT NULL,status TEXT NOT NULL,
                attempts INTEGER NOT NULL,outputs_json TEXT NOT NULL,error TEXT NOT NULL,
                started_at TEXT NOT NULL,finished_at TEXT NOT NULL,
                UNIQUE(automation_id,trigger_key))""")

    def create(self, name: str, trigger_type: str, trigger_value: str, actions, *, retries=2, enabled=True):
        trigger_type = str(trigger_type).lower().strip()
        if trigger_type not in {"once", "daily", "interval", "cron", "event", "voice"}:
            raise ValueError("trigger_type non supportato")
        trigger_value = str(trigger_value).strip()
        if trigger_type == "once":
            try:
                datetime.fromisoformat(trigger_value)
            except ValueError as exc:
                raise ValueError("once trigger must be an ISO datetime") from exc
        elif trigger_type == "daily":
            try:
                datetime.strptime(trigger_value, "%H:%M")
            except ValueError as exc:
                raise ValueError("daily trigger must use HH:MM") from exc
        elif trigger_type == "cron" and len(trigger_value.split()) != 5:
            raise ValueError("cron trigger must contain 5 fields")
        elif trigger_type == "interval":
            try:
                if int(trigger_value) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError("interval trigger must be a positive number of seconds") from exc
        normalized = [({"command": item} if isinstance(item, str) else dict(item)) for item in actions]
        if (
            not name.strip()
            or not normalized
            or any(not item.get("command") and not item.get("skill") for item in normalized)
        ):
            raise ValueError("nome e azioni valide sono obbligatori")
        automation_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO automations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    automation_id,
                    name.strip(),
                    trigger_type,
                    trigger_value,
                    json.dumps(normalized, ensure_ascii=False),
                    int(enabled),
                    max(0, int(retries)),
                    now,
                    now,
                ),
            )
        return automation_id

    def list(self, enabled_only=False):
        query = "SELECT * FROM automations" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY created_at"
        with self._connect() as db:
            rows = db.execute(query).fetchall()
        decoded = []
        for row in rows:
            try:
                decoded.append(self._decode(row))
            except (TypeError, ValueError, json.JSONDecodeError):
                # A corrupt persisted automation must never block healthy rows
                # or become executable with an implicitly empty action list.
                continue
        return decoded

    def set_enabled(self, automation_id: str, enabled: bool):
        with self._lock, self._connect() as db:
            changed = db.execute(
                "UPDATE automations SET enabled=?,updated_at=? WHERE id=?",
                (int(enabled), datetime.now().isoformat(), automation_id),
            ).rowcount
        return bool(changed)

    def due(self, now: datetime | None = None):
        now = now or datetime.now()
        ready = []
        for item in self.list(enabled_only=True):
            kind, value = item["trigger_type"], item["trigger_value"]
            try:
                if (
                    kind == "once"
                    and now >= datetime.fromisoformat(value)
                    and not self._has_run(item["id"], f"once:{value}")
                ):
                    ready.append((item, f"once:{value}"))
                elif kind == "daily" and now.strftime("%H:%M") == value:
                    key = f"daily:{now:%Y-%m-%d}:{value}"
                    if not self._has_run(item["id"], key):
                        ready.append((item, key))
                elif kind == "interval":
                    seconds = int(value)
                    if seconds > 0 and self._interval_due(item["id"], seconds, now):
                        ready.append((item, f"interval:{int(now.timestamp()) // seconds}"))
                elif kind == "cron" and self._cron_matches(value, now):
                    key = f"cron:{now:%Y-%m-%dT%H:%M}"
                    if not self._has_run(item["id"], key):
                        ready.append((item, key))
            except (TypeError, ValueError, OverflowError):
                # Legacy/corrupt rows must not prevent valid schedules from running.
                continue
        return ready

    def handle_event(self, event: str, payload: dict | None = None):
        event = str(event or "").casefold()
        payload = payload or {}
        results = []
        for item in self.list(enabled_only=True):
            expected = str(item["trigger_value"]).casefold()
            matches = item["trigger_type"] == "event" and expected == event
            matches = matches or (
                item["trigger_type"] == "voice" and expected in str(payload.get("text", "")).casefold()
            )
            if matches:
                key = str(
                    payload.get("event_id") or f"{event}:{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
                )
                results.append(self.execute(item["id"], key))
        return results

    def run_due(self, now: datetime | None = None):
        return [self.execute(item["id"], key) for item, key in self.due(now)]

    def execute(self, automation_id: str, trigger_key: str):
        item = next((row for row in self.list() if row["id"] == automation_id), None)
        if not item:
            raise KeyError(automation_id)
        if self._paused.is_set():
            return AutomationResult(automation_id, "cancelled", 0, error="automation engine paused")
        with self._lock, self._connect() as db:
            reservation_reused = False
            prior = db.execute(
                "SELECT * FROM automation_runs WHERE automation_id=? AND trigger_key=?", (automation_id, trigger_key)
            ).fetchone()
            if prior:
                if str(prior["status"]) == "running":
                    try:
                        age = (datetime.now() - datetime.fromisoformat(str(prior["started_at"]))).total_seconds()
                    except (TypeError, ValueError, OverflowError):
                        age = STALE_RUNNING_SECONDS + 1
                    if age > STALE_RUNNING_SECONDS:
                        now = datetime.now().isoformat()
                        db.execute(
                            "UPDATE automation_runs SET status=?,attempts=?,outputs_json=?,error=?,started_at=?,finished_at=? WHERE automation_id=? AND trigger_key=?",
                            ("running", 0, "[]", "", now, now, automation_id, trigger_key),
                        )
                        prior = None
                        reservation_reused = True
                if prior:
                    outputs = self._decode_outputs(prior["outputs_json"])
                    return AutomationResult(
                        automation_id,
                        str(prior["status"]),
                        int(prior["attempts"]),
                        tuple(outputs),
                        str(prior["error"]),
                        True,
                    )
            if not item["enabled"]:
                return AutomationResult(automation_id, "disabled", 0)
            if not reservation_reused:
                now = datetime.now().isoformat()
                db.execute(
                    "INSERT INTO automation_runs VALUES(?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, item["id"], trigger_key, "running", 0, "[]", "", now, now),
                )
        if self.dispatcher is None:
            return self._record(item, trigger_key, "failed", 0, [], "dispatcher non configurato")
        attempts, error = 0, ""
        outputs: list[dict[str, Any]] = []
        for attempt in range(item["retries"] + 1):
            attempts = attempt + 1
            outputs = []
            try:
                for action in item["actions"]:
                    if self._paused.is_set():
                        return self._record(item, trigger_key, "cancelled", attempts, outputs, "emergency stop")
                    result = dict(self.dispatcher(dict(action)) or {})
                    outputs.append(result)
                    if not result.get("success", result.get("successo", False)):
                        raise RuntimeError(str(result.get("message") or result.get("messaggio") or "azione fallita"))
                result = self._record(item, trigger_key, "completed", attempts, outputs, "")
                if item["trigger_type"] == "once":
                    self.set_enabled(automation_id, False)
                return result
            except Exception as exc:
                error = redact(f"{type(exc).__name__}: {exc}")
                if attempt < item["retries"]:
                    self._sleep(min(2**attempt, 30))
        return self._record(item, trigger_key, "failed", attempts, outputs, error)

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def history(self, limit=100):
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError, OverflowError):
            limit = 100
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM automation_runs ORDER BY finished_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(row), "outputs": self._decode_outputs(row["outputs_json"])} for row in rows]

    def report(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT status,COUNT(*) count,AVG(attempts) average_attempts FROM automation_runs GROUP BY status"
            ).fetchall()
        return {
            "automations": len(self.list()),
            "runs": {
                row["status"]: {"count": row["count"], "average_attempts": row["average_attempts"]} for row in rows
            },
            "event_queue": self._event_queue.qsize(),
            "dropped_events": self._dropped_events,
        }

    def _record(self, item, trigger_key, status, attempts, outputs, error):
        now = datetime.now().isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE automation_runs SET status=?,attempts=?,outputs_json=?,error=?,finished_at=? WHERE automation_id=? AND trigger_key=?",
                (status, attempts, json.dumps(outputs, ensure_ascii=False), error, now, item["id"], trigger_key),
            )
        return AutomationResult(item["id"], status, attempts, tuple(outputs), error)

    def _interval_due(self, automation_id, seconds, now):
        bucket = int(now.timestamp()) // seconds
        return not self._has_run(automation_id, f"interval:{bucket}")

    def _has_run(self, automation_id, trigger_key):
        with self._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM automation_runs WHERE automation_id=? AND trigger_key=?",
                    (automation_id, trigger_key),
                ).fetchone()
                is not None
            )

    @staticmethod
    def _cron_matches(expression, now):
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("cron richiede 5 campi")
        values = [now.minute, now.hour, now.day, now.month, now.weekday()]
        return all(field == "*" or str(value) in field.split(",") for field, value in zip(fields, values, strict=True))

    @staticmethod
    def _decode(row):
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["actions"] = json.loads(value.pop("actions_json"))
        return value

    @staticmethod
    def _decode_outputs(raw):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
