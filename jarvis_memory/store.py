from __future__ import annotations
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    SESSION = "session"
    PREFERENCE = "preference"
    TASK = "task"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


_SENSITIVE = re.compile(
    r"(?i)(password|passphrase|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|numero carta|credit card)\s*[:=]?\s*\S+"
)


def _vector(value: str, dims: int = 256):
    text = _normalize(value)
    features = re.findall(r"\w+", text) + [text[index : index + 3] for index in range(max(0, len(text) - 2))]
    vector: dict[int, int] = {}
    for feature in features:
        index = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=2).digest(), "big") % dims
        vector[index] = vector.get(index, 0) + 1
    norm = math.sqrt(sum(item * item for item in vector.values())) or 1
    return {key: value / norm for key, value in vector.items()}


def _cosine(left, right):
    return sum(value * right.get(key, 0) for key, value in left.items())


class WorkingMemory:
    def __init__(self):
        self._values = {}
        self._lock = threading.RLock()

    def set(self, key: str, value, ttl: float | None = None) -> None:
        with self._lock:
            self._values[key] = (deepcopy(value), None if ttl is None else time.monotonic() + max(0, ttl))

    def get(self, key: str, default=None):
        with self._lock:
            item = self._values.get(key)
            if not item:
                return deepcopy(default)
            if item[1] is not None and time.monotonic() >= item[1]:
                self._values.pop(key, None)
                return deepcopy(default)
            return deepcopy(item[0])

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            snapshot = {}
            for key, (value, expires_at) in list(self._values.items()):
                if expires_at is not None and now >= expires_at:
                    self._values.pop(key, None)
                    continue
                snapshot[key] = deepcopy(value)
            return snapshot


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.working = WorkingMemory()
        self._migrate()

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _migrate(self):
        with self._lock, self._connection() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS memory_items(id TEXT PRIMARY KEY,kind TEXT NOT NULL,content TEXT NOT NULL,normalized_hash TEXT NOT NULL,metadata_json TEXT NOT NULL,source TEXT NOT NULL,confidence REAL NOT NULL,importance REAL NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_used_at TEXT,use_count INTEGER NOT NULL DEFAULT 0,expires_at TEXT,active INTEGER NOT NULL DEFAULT 1,UNIQUE(kind,normalized_hash))"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_rank ON memory_items(active,kind,importance DESC,confidence DESC,updated_at DESC)"
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS knowledge_edges(source_id TEXT NOT NULL,relation TEXT NOT NULL,target_id TEXT NOT NULL,confidence REAL NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(source_id,relation,target_id),FOREIGN KEY(source_id) REFERENCES memory_items(id),FOREIGN KEY(target_id) REFERENCES memory_items(id))"""
            )

    def remember(
        self,
        content: str,
        *,
        kind: MemoryKind | str = MemoryKind.SEMANTIC,
        source: str = "user",
        confidence: float = 1,
        importance: float = 0.7,
        metadata: dict | None = None,
        expires_at: str | None = None,
    ) -> dict:
        value = str(content).strip()
        if not value:
            raise ValueError("memory content cannot be empty")
        if _SENSITIVE.search(value) or _SENSITIVE.search(json.dumps(metadata or {}, ensure_ascii=False)):
            raise ValueError("I segreti non possono essere memorizzati")
        kind = MemoryKind(kind)
        normalized = _normalize(value)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        now = _now()
        identity = hashlib.sha256(f"{kind}:{digest}".encode()).hexdigest()[:24]
        confidence = max(0, min(1, float(confidence)))
        importance = max(0, min(1, float(importance)))
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT id,use_count FROM memory_items WHERE kind=? AND normalized_hash=?", (kind.value, digest)
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE memory_items SET updated_at=?,active=1,confidence=max(confidence,?),importance=max(importance,?),metadata_json=? WHERE id=?",
                    (now, confidence, importance, json.dumps(metadata or {}, ensure_ascii=False), row["id"]),
                )
                return {"id": row["id"], "deduplicated": True}
            db.execute(
                "INSERT INTO memory_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    kind.value,
                    value,
                    digest,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    source,
                    confidence,
                    importance,
                    now,
                    now,
                    now,
                    0,
                    expires_at,
                    1,
                ),
            )
        return {"id": identity, "deduplicated": False}

    def search(self, query: str = "", *, kind: MemoryKind | str | None = None, limit: int = 20) -> list[dict]:
        now = _now()
        tokens = [x for x in re.findall(r"\w+", _normalize(query)) if len(x) > 1]
        query_vector = _vector(query) if tokens else {}
        sql = "SELECT * FROM memory_items WHERE active=1 AND (expires_at IS NULL OR expires_at>?)"
        params = [now]
        if kind:
            sql += " AND kind=?"
            params.append(MemoryKind(kind).value)
        rows = []
        with self._lock, self._connection() as db:
            for row in db.execute(sql, params).fetchall():
                item = dict(row)
                normalized = _normalize(item["content"])
                lexical = 1 if not tokens else sum(token in normalized for token in tokens) / len(tokens)
                vector_score = 1 if not tokens else _cosine(query_vector, _vector(normalized))
                relevance = max(lexical, vector_score)
                if tokens and relevance < 0.05:
                    continue
                age_days = max(
                    0, (datetime.now(timezone.utc) - datetime.fromisoformat(item["updated_at"])).total_seconds() / 86400
                )
                recency = 1 / (1 + age_days / 30)
                item["score"] = round(
                    0.45 * relevance + 0.25 * item["importance"] + 0.2 * item["confidence"] + 0.1 * recency, 6
                )
                item["metadata"] = json.loads(item.pop("metadata_json"))
                rows.append(item)
            rows.sort(key=lambda x: (x["score"], x["updated_at"]), reverse=True)
            rows = rows[: max(1, min(int(limit), 100))]
            db.executemany(
                "UPDATE memory_items SET use_count=use_count+1,last_used_at=? WHERE id=?",
                [(now, x["id"]) for x in rows],
            )
        return rows

    def connect(self, source_id: str, relation: str, target_id: str, confidence: float = 1) -> None:
        if source_id == target_id:
            raise ValueError("self relations are not allowed")
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO knowledge_edges VALUES(?,?,?,?,?)",
                (source_id, str(relation).strip(), target_id, max(0, min(1, float(confidence))), _now()),
            )

    def neighbors(self, memory_id: str) -> list[dict]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT e.relation,e.confidence,m.id,m.kind,m.content FROM knowledge_edges e JOIN memory_items m ON m.id=e.target_id WHERE e.source_id=? AND m.active=1""",
                (memory_id,),
            ).fetchall()
        return [dict(x) for x in rows]

    def forget(self, memory_id: str) -> bool:
        with self._lock, self._connection() as db:
            return bool(
                db.execute("UPDATE memory_items SET active=0,updated_at=? WHERE id=?", (_now(), memory_id)).rowcount
            )

    def consolidate(self) -> dict:
        now = _now()
        with self._lock, self._connection() as db:
            expired = db.execute(
                "UPDATE memory_items SET active=0,updated_at=? WHERE active=1 AND expires_at IS NOT NULL AND expires_at<=?",
                (now, now),
            ).rowcount
            promoted = db.execute(
                "UPDATE memory_items SET importance=min(1.0,importance+0.05),updated_at=? WHERE active=1 AND use_count>=5",
                (now,),
            ).rowcount
        return {"expired": expired, "promoted": promoted}

    def migrate_legacy(self) -> dict:
        """Idempotently imports the existing personal_memory schema in-place."""
        memories = []
        episodes = []
        with self._lock, self._connection() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "memories" in tables:
                memories = [dict(x) for x in db.execute("SELECT * FROM memories WHERE active=1").fetchall()]
            if "episodes" in tables:
                episodes = [dict(x) for x in db.execute("SELECT * FROM episodes").fetchall()]
        imported = 0
        skipped_sensitive = 0
        for row in memories:
            try:
                result = self.remember(
                    row["content"],
                    kind=MemoryKind.SEMANTIC,
                    source=row.get("source", "legacy"),
                    confidence=row.get("confidence", 1),
                    importance=row.get("importance", 0.7),
                    metadata={"legacy_category": row.get("category")},
                    expires_at=row.get("expires_at"),
                )
                imported += not result["deduplicated"]
            except ValueError:
                skipped_sensitive += 1
        for row in episodes:
            content = f"Utente: {row['user_text']}\nAssistente: {row['assistant_text']}"
            try:
                result = self.remember(
                    content,
                    kind=MemoryKind.EPISODIC,
                    source="legacy_conversation",
                    importance=0.5,
                    metadata={"legacy_created_at": row.get("created_at")},
                )
                imported += not result["deduplicated"]
            except ValueError:
                skipped_sensitive += 1
        return {
            "found": len(memories) + len(episodes),
            "imported": int(imported),
            "skipped_sensitive": skipped_sensitive,
        }
