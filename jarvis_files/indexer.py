from __future__ import annotations

import math
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_TOKEN = re.compile(r"[\wàèéìòù]{2,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IndexStats:
    scanned: int
    indexed: int
    skipped_sensitive: int
    errors: int
    duration_ms: int


class FileIndexer:
    TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".py",
        ".json",
        ".csv",
        ".log",
        ".ini",
        ".toml",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".js",
    }
    SENSITIVE_NAMES = {".env", "credentials.json", "password.txt", "id_rsa", "id_ed25519", "secrets.json"}
    SENSITIVE_PARTS = {".git", ".runtime-env", "venv", "node_modules", "appdata", "credentials", "secrets", "backups"}

    def __init__(self, database: Path, roots: list[Path], *, max_content_bytes: int = 1_000_000):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.roots = tuple(Path(root).resolve() for root in roots)
        self.max_content_bytes = max(4096, int(max_content_bytes))
        self._migrate()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self):
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,name TEXT NOT NULL,extension TEXT NOT NULL,
                       size INTEGER NOT NULL,modified REAL NOT NULL,indexed REAL NOT NULL,content TEXT NOT NULL)"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension)")

    def scan(self, *, limit: int = 100_000) -> IndexStats:
        started = time.monotonic()
        scanned = indexed = sensitive = errors = 0
        seen = set()
        with self._connect() as db:
            for root in self.roots:
                if not root.exists():
                    continue
                for path in root.rglob("*"):
                    if scanned >= limit:
                        break
                    if not path.is_file():
                        continue
                    scanned += 1
                    try:
                        resolved = path.resolve()
                        seen.add(str(resolved))
                        if self._sensitive(resolved):
                            sensitive += 1
                            continue
                        stat = resolved.stat()
                        prior = db.execute("SELECT size,modified FROM files WHERE path=?", (str(resolved),)).fetchone()
                        if prior and prior["size"] == stat.st_size and prior["modified"] == stat.st_mtime:
                            continue
                        content = self._content(resolved, stat.st_size)
                        db.execute(
                            """INSERT INTO files VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                                   name=excluded.name,extension=excluded.extension,size=excluded.size,modified=excluded.modified,
                                   indexed=excluded.indexed,content=excluded.content""",
                            (
                                str(resolved),
                                resolved.name,
                                resolved.suffix.lower(),
                                stat.st_size,
                                stat.st_mtime,
                                time.time(),
                                content,
                            ),
                        )
                        indexed += 1
                    except (OSError, UnicodeError, sqlite3.Error):
                        errors += 1
            for row in db.execute("SELECT path FROM files").fetchall():
                if row["path"] not in seen and any(self._within(Path(row["path"]), root) for root in self.roots):
                    db.execute("DELETE FROM files WHERE path=?", (row["path"],))
        return IndexStats(scanned, indexed, sensitive, errors, int((time.monotonic() - started) * 1000))

    def search(
        self,
        query: str,
        *,
        extension: str | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        tokens = {value.casefold() for value in _TOKEN.findall(str(query))}
        if not tokens:
            return []
        clauses = []
        values: list[object] = []
        if extension:
            clauses.append("extension=?")
            values.append(extension if extension.startswith(".") else f".{extension}")
        if modified_after:
            clauses.append("modified>=?")
            values.append(modified_after.timestamp())
        if modified_before:
            clauses.append("modified<=?")
            values.append(modified_before.timestamp())
        sql = "SELECT * FROM files" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        with self._connect() as db:
            rows = db.execute(sql, values).fetchall()
        results = []
        for row in rows:
            haystack = f"{row['name']} {row['path']} {row['content']}".casefold()
            hits = sum(haystack.count(token) for token in tokens)
            if not hits:
                continue
            name_hits = sum(token in row["name"].casefold() for token in tokens)
            score = name_hits * 4 + math.log1p(hits) + min(row["modified"] / 10**10, 0.2)
            results.append({**dict(row), "score": round(score, 4)})
        results.sort(key=lambda item: (item["score"], item["modified"]), reverse=True)
        return results[: max(1, min(int(limit), 100))]

    def _content(self, path: Path, size: int) -> str:
        if path.suffix.lower() not in self.TEXT_EXTENSIONS or size > self.max_content_bytes:
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        # Never retain common inline secret assignments even in otherwise safe source files.
        return "\n".join(
            line for line in text.splitlines() if not re.search(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]", line)
        )[: self.max_content_bytes]

    def _sensitive(self, path: Path) -> bool:
        if path == self.database or path.name.casefold() in self.SENSITIVE_NAMES:
            return True
        for root in self.roots:
            if self._within(path, root):
                relative_parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
                return bool(relative_parts & self.SENSITIVE_PARTS)
        return True

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        return path == root or root in path.parents
