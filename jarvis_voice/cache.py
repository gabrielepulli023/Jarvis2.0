from __future__ import annotations
import hashlib
import os
import shutil
import tempfile
import threading
from pathlib import Path


class TTSCache:
    """Bounded atomic cache for generated speech audio."""

    def __init__(self, root: Path, max_entries: int = 120, min_size: int = 128):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_entries = max(1, int(max_entries))
        self.min_size = max(1, int(min_size))
        self._lock = threading.RLock()

    @staticmethod
    def key(signature: str) -> str:
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    def restore(self, signature: str, target: Path) -> bool:
        source = self.root / (self.key(signature) + ".mp3")
        with self._lock:
            if not source.exists() or source.stat().st_size < self.min_size:
                return False
            shutil.copy2(source, target)
            os.utime(source, None)
            return True

    def store(self, signature: str, source: Path) -> bool:
        source = Path(source)
        if not source.exists() or source.stat().st_size < self.min_size:
            return False
        target = self.root / (self.key(signature) + ".mp3")
        with self._lock:
            handle, temp_name = tempfile.mkstemp(prefix="tts_", suffix=".tmp", dir=self.root)
            os.close(handle)
            temp = Path(temp_name)
            try:
                shutil.copy2(source, temp)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            self.prune()
            return True

    def prune(self) -> int:
        with self._lock:
            files = sorted(self.root.glob("*.mp3"), key=lambda path: path.stat().st_mtime, reverse=True)
            removed = 0
            for path in files[self.max_entries :]:
                path.unlink(missing_ok=True)
                removed += 1
            return removed

    def stats(self) -> dict:
        with self._lock:
            files = list(self.root.glob("*.mp3"))
            return {
                "entries": len(files),
                "bytes": sum(x.stat().st_size for x in files),
                "max_entries": self.max_entries,
            }
