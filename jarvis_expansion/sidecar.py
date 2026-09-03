from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from settings_store import get_setting


class ExpansionSidecarManager:
    """Own the isolated expansion runtime without polluting JARVIS' main Python env."""

    KEY_FILE = ".jarvis_expansion_key"
    LOG_FILE = ".jarvis_expansion.log"

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / "external_integrations" / "expansion"
        self.python_exe = self.root / ".expansion-env" / "Scripts" / "python.exe"
        self.server_script = self.root / "expansion_server.py"
        self.config_path = self.root / "expansion_config.json"
        self.key_path = self.root / self.KEY_FILE
        self.log_path = self.root / self.LOG_FILE
        self.data_dir = self.project_root / "data" / "expansion"
        self.base_url = str(get_setting("expansion_base_url", "http://127.0.0.1:5199") or "http://127.0.0.1:5199").rstrip("/")
        self.auto_start = bool(get_setting("expansion_auto_start", True))
        self._process: subprocess.Popen | None = None
        self._log_handle = None
        self._started = False
        self._last_error = ""
        self._key = self._ensure_key() if self.root.exists() else ""

    def _read_key(self) -> str:
        try:
            return self.key_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _ensure_key(self) -> str:
        key = self._read_key()
        if key:
            return key
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            key = secrets.token_urlsafe(32)
            self.key_path.write_text(key, encoding="utf-8")
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return key
        except OSError as exc:
            self._last_error = f"Impossibile creare chiave Expansion: {exc}"
            return ""

    def _endpoint(self) -> tuple[str, int] | None:
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
            self._last_error = "Expansion sidecar può ascoltare solo su localhost HTTP."
            return None
        return parsed.hostname or "127.0.0.1", parsed.port or 5199

    def _healthy(self) -> bool:
        if not self._key:
            return False
        req = Request(
            self.base_url + "/health",
            headers={"X-JARVIS-Expansion-Key": self._key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(req, timeout=1.5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
                return bool(data.get("success")) and str(data.get("status", "")).lower() == "healthy"
        except (HTTPError, URLError, OSError, ValueError):
            return False

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            return False

    @staticmethod
    def _creationflags() -> int:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def start(self) -> bool:
        if not self.auto_start:
            return False
        endpoint = self._endpoint()
        if endpoint is None:
            return False
        host, port = endpoint
        if not self.server_script.exists():
            self._last_error = "expansion_server.py non trovato."
            return False
        if not self.python_exe.exists():
            self._last_error = "Ambiente .expansion-env non installato. Esegui 'INSTALLA ESPANSIONI JARVIS.cmd'."
            return False
        if not self._key:
            self._key = self._ensure_key()
        if not self._key:
            return False

        if self._healthy():
            self._last_error = ""
            return True
        if self._port_open(host, port):
            self._last_error = f"Porta Expansion {port} occupata da un altro processo."
            return False

        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._log_handle = open(self.log_path, "a", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self._process = subprocess.Popen(
            [
                str(self.python_exe), str(self.server_script),
                "--host", host,
                "--port", str(port),
                "--token", self._key,
                "--config", str(self.config_path),
                "--data-dir", str(self.data_dir),
            ],
            cwd=str(self.root),
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=self._creationflags(),
        )
        self._started = True
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            if self._healthy():
                self._last_error = ""
                return True
            if self._process.poll() is not None:
                break
            time.sleep(0.25)
        self._last_error = f"Expansion sidecar non avviato. Log: {self.log_path}"
        self.stop()
        return False

    def stop(self) -> None:
        proc = self._process
        if self._started and proc is not None and proc.poll() is None:
            if sys.platform == "win32":
                try:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=8,
                        check=False,
                    )
                except Exception:
                    pass
            else:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._process = None
        self._started = False
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def snapshot(self) -> dict:
        return {
            "enabled": self.auto_start,
            "healthy": self._healthy(),
            "base_url": self.base_url,
            "started": self._started,
            "pid": self._process.pid if self._process is not None and self._process.poll() is None else None,
            "error": self._last_error,
            "log": str(self.log_path),
        }
