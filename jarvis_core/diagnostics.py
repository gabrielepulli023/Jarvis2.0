from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


class DiagnosticsRunner:
    def __init__(self, project_root: Path, data_root: Path):
        self.project_root = Path(project_root)
        self.data_root = Path(data_root)

    def run(self):
        checks = []
        checks.append(
            self._check(
                "python",
                sys.version_info >= (3, 12),
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
        )
        checks.append(self._writable())
        checks.extend(self._imports())
        checks.extend(self._databases())
        critical = ["main.py", "brain.py", "hud.py", "jarvis_core/runtime.py"]
        checks.append(
            self._check(
                "critical_files", all((self.project_root / name).is_file() for name in critical), ", ".join(critical)
            )
        )
        failed = [row for row in checks if row["status"] == "failed"]
        degraded = [row for row in checks if row["status"] == "degraded"]
        status = "failed" if failed else "degraded" if degraded else "healthy"
        return {
            "status": status,
            "checks": checks,
            "summary": {"total": len(checks), "failed": len(failed), "degraded": len(degraded)},
        }

    @staticmethod
    def _check(name, success, detail, degraded=False):
        return {
            "name": name,
            "status": "healthy" if success else "degraded" if degraded else "failed",
            "detail": str(detail),
        }

    def _writable(self):
        try:
            self.data_root.mkdir(parents=True, exist_ok=True)
            probe = self.data_root / ".diagnostic-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return self._check("data_directory", True, self.data_root)
        except OSError as exc:
            return self._check("data_directory", False, exc)

    def _imports(self):
        required = ("PySide6", "openai", "sounddevice", "vosk", "psutil", "cv2")
        return [
            self._check(f"dependency:{name}", importlib.util.find_spec(name) is not None, "installed")
            for name in required
        ]

    def _databases(self):
        rows = []
        for path in self.data_root.rglob("*.db") if self.data_root.exists() else ():
            db = None
            try:
                db = sqlite3.connect(path)
                result = db.execute("PRAGMA integrity_check").fetchone()[0]
                rows.append(self._check(f"sqlite:{path.name}", result == "ok", result))
            except sqlite3.Error as exc:
                rows.append(self._check(f"sqlite:{path.name}", False, exc))
            finally:
                if db is not None:
                    db.close()
        return rows or [self._check("sqlite", False, "nessun database ancora creato", degraded=True)]
