from __future__ import annotations
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .graph import TaskGraph


class MissionStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrate()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self):
        with self._lock, self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
            if db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
                db.execute("INSERT INTO schema_version VALUES (?)", (self.SCHEMA_VERSION,))
            db.execute("""CREATE TABLE IF NOT EXISTS missions(
                id TEXT PRIMARY KEY, objective TEXT NOT NULL, status TEXT NOT NULL, graph_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute(
                """CREATE TABLE IF NOT EXISTS mission_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL, event TEXT NOT NULL,
                payload_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(mission_id) REFERENCES missions(id))"""
            )

    def create(self, objective: str, graph: TaskGraph) -> str:
        mission_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(graph.as_dict(), ensure_ascii=False)
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT INTO missions VALUES(?,?,?,?,?,?,?)",
                (mission_id, objective, "pending", payload, "{}", now, now),
            )
            db.execute(
                "INSERT INTO mission_events(mission_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                (mission_id, "mission.created", "{}", now),
            )
        return mission_id

    def save(
        self,
        mission_id: str,
        graph: TaskGraph,
        *,
        status: str,
        checkpoint: dict | None = None,
        event: str = "mission.updated",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        graph_json = json.dumps(graph.as_dict(), ensure_ascii=False)
        checkpoint_json = json.dumps(checkpoint or {}, ensure_ascii=False)
        with self._lock, self._connection() as db:
            changed = db.execute(
                "UPDATE missions SET status=?,graph_json=?,checkpoint_json=?,updated_at=? WHERE id=?",
                (status, graph_json, checkpoint_json, now, mission_id),
            ).rowcount
            if not changed:
                raise KeyError(mission_id)
            db.execute(
                "INSERT INTO mission_events(mission_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                (mission_id, event, checkpoint_json, now),
            )

    def get(self, mission_id: str) -> dict | None:
        with self._lock, self._connection() as db:
            row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["graph"] = json.loads(value.pop("graph_json"))
        value["checkpoint"] = json.loads(value.pop("checkpoint_json"))
        return value

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT id,objective,status,created_at,updated_at FROM missions ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def events(self, mission_id: str, limit: int = 50) -> list[dict]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                "SELECT event,payload_json,created_at FROM mission_events WHERE mission_id=? ORDER BY id DESC LIMIT ?",
                (str(mission_id), max(1, min(int(limit), 500))),
            ).fetchall()
        result = []
        for row in reversed(rows):
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            result.append(value)
        return result
