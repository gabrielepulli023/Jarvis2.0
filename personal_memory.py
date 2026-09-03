import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from app_paths import data_path
from settings_store import get_setting


DB_PATH = data_path("jarvis_memory.db")
_LOCK = threading.RLock()


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(active, category)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    for name, definition in {
        "importance": "REAL NOT NULL DEFAULT 0.7",
        "expires_at": "TEXT",
        "last_accessed_at": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_text TEXT NOT NULL,
            assistant_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return conn


def remember(content, category="preference", source="user", confidence=1.0, importance=None, expires_at=None):
    if get_setting("privacy_mode", False):
        return {"successo": False, "messaggio": "Modalità privata: memoria non salvata."}
    value = str(content or "").strip()
    if not value:
        return {"successo": False, "messaggio": "Memoria vuota."}
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK, _connect() as conn:
        duplicate = conn.execute(
            "SELECT id FROM memories WHERE active=1 AND lower(content)=lower(?)", (value,)
        ).fetchone()
        if duplicate:
            conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, duplicate["id"]))
            return {"successo": True, "id": duplicate["id"], "messaggio": "Informazione già ricordata."}
        weight = float(importance if importance is not None else (1.0 if source == "user" else 0.7))
        cursor = conn.execute(
            "INSERT INTO memories(category,content,source,confidence,created_at,updated_at,importance,expires_at,last_accessed_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (str(category), value, str(source), float(confidence), now, now, max(0.0, min(weight, 1.0)), expires_at, now),
        )
        return {"successo": True, "id": cursor.lastrowid, "messaggio": "Informazione memorizzata."}


def search(query="", category=None, limit=20):
    query = str(query or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    sql = "SELECT * FROM memories WHERE active=1 AND (expires_at IS NULL OR expires_at>?)"
    params = [now]
    if category:
        sql += " AND category=?"; params.append(str(category))
    if query:
        sql += " AND lower(content) LIKE lower(?)"; params.append(f"%{query}%")
    sql += " ORDER BY importance DESC, confidence DESC, updated_at DESC LIMIT ?"; params.append(max(1, min(int(limit), 100)))
    with _LOCK, _connect() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        if rows:
            conn.executemany("UPDATE memories SET last_accessed_at=? WHERE id=?", [(now, row["id"]) for row in rows])
        return rows


def forget(memory_id):
    with _LOCK, _connect() as conn:
        cursor = conn.execute("UPDATE memories SET active=0,updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), int(memory_id)))
        return {"successo": cursor.rowcount > 0, "messaggio": "Memoria rimossa." if cursor.rowcount else "Memoria non trovata."}


def context(limit=30):
    if get_setting("privacy_mode", False):
        return ""
    rows = search(limit=limit)
    if not rows:
        return ""
    return "\n".join(
        f"- [{row['category']} | fonte={row['source']} | affidabilità={row['confidence']:.2f}] {row['content']}"
        for row in rows
    )


def record_episode(user_text, assistant_text):
    if get_setting("privacy_mode", False):
        return False
    user_text = str(user_text or "").strip()
    assistant_text = str(assistant_text or "").strip()
    if not user_text or not assistant_text:
        return False
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO episodes(user_text,assistant_text,created_at) VALUES(?,?,?)",
            (user_text[:4000], assistant_text[:8000], datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("DELETE FROM episodes WHERE id NOT IN (SELECT id FROM episodes ORDER BY id DESC LIMIT 200)")
    return True


def recent_episodes(limit=5):
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM episodes ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 20)),)).fetchall()
    return [dict(row) for row in reversed(rows)]


def learn_explicit(text):
    value = str(text or "").strip()
    lower = value.lower()
    markers = ("preferisco ", "mi chiamo ", "il mio nome è ", "il mio nome e ", "lavoro come ")
    if any(marker in lower for marker in markers):
        return remember(value, category="preference" if "preferisco" in lower else "profile", source="conversation")
    return None


def export_json(path=None):
    target = Path(path) if path else DB_PATH.with_name("jarvis_memory_export.json")
    target.write_text(json.dumps(search(limit=10000), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
