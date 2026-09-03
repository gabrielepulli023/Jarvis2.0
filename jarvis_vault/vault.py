from __future__ import annotations
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from jarvis_identity.crypto import protect, unprotect


@dataclass(frozen=True, slots=True)
class VaultEntry:
    name: str
    created_at: float
    updated_at: float


class CredentialVault:
    """DPAPI-backed per-user secret store. Values are never exposed by inventory APIs."""

    _NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS credentials(name TEXT PRIMARY KEY,encrypted BLOB NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL)"
            )

    @classmethod
    def _validate_name(cls, name: str) -> str:
        value = str(name).strip()
        if not cls._NAME.fullmatch(value):
            raise ValueError("Nome credenziale non valido")
        return value

    def put(self, name: str, value: str | bytes) -> VaultEntry:
        key = self._validate_name(name)
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if not raw or len(raw) > 1_000_000:
            raise ValueError("Valore credenziale vuoto o troppo grande")
        encrypted = protect(raw)
        now = time.time()
        with self._lock, sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO credentials VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET encrypted=excluded.encrypted,updated_at=excluded.updated_at",
                (key, encrypted, now, now),
            )
            row = db.execute("SELECT name,created_at,updated_at FROM credentials WHERE name=?", (key,)).fetchone()
        return VaultEntry(str(row[0]), float(row[1]), float(row[2]))

    def get(self, name: str) -> bytes:
        key = self._validate_name(name)
        with self._lock, sqlite3.connect(self.path) as db:
            row = db.execute("SELECT encrypted FROM credentials WHERE name=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return unprotect(bytes(row[0]))

    def delete(self, name: str) -> bool:
        key = self._validate_name(name)
        with self._lock, sqlite3.connect(self.path) as db:
            cursor = db.execute("DELETE FROM credentials WHERE name=?", (key,))
        return cursor.rowcount > 0

    def list(self) -> list[VaultEntry]:
        with self._lock, sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT name,created_at,updated_at FROM credentials ORDER BY name").fetchall()
        return [VaultEntry(str(name), float(created), float(updated)) for name, created, updated in rows]
