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
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from settings_store import get_setting


class UFOSidecarManager:
    """Own the local Microsoft UFO server/client lifecycle for JARVIS.

    UFO's HTTP/WebSocket API requires a server API key.  We keep a dedicated
    random localhost-only key beside the UFO checkout, pass it to both server
    and client, and let JARVIS' HTTP adapter read the same key file.
    """

    KEY_FILE = ".jarvis_ufo_server_key"
    LOG_FILE = ".jarvis_ufo_sidecar.log"

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root).resolve()
        self.ufo_dir = self.project_root / "external_integrations" / "UFO"
        self.python_exe = self.ufo_dir / ".ufo-env" / "Scripts" / "python.exe"
        self.key_path = self.ufo_dir / self.KEY_FILE
        self.log_path = self.ufo_dir / self.LOG_FILE
        self.client_id = str(get_setting("ufo_client_id", "jarvis_windows") or "jarvis_windows").strip()
        self.base_url = str(get_setting("ufo_base_url", "http://127.0.0.1:5000") or "http://127.0.0.1:5000").rstrip("/")
        self.auto_start = bool(get_setting("ufo_auto_start", True))
        self._server: subprocess.Popen | None = None
        self._client: subprocess.Popen | None = None
        self._log_handle = None
        self._started_server = False
        self._started_client = False
        self._last_error = ""
        self._key = self._ensure_key() if self.auto_start and self.ufo_dir.exists() else self._read_key()

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
            self.ufo_dir.mkdir(parents=True, exist_ok=True)
            key = secrets.token_urlsafe(32)
            self.key_path.write_text(key, encoding="utf-8")
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return key
        except OSError as exc:
            self._last_error = f"Impossibile creare la chiave locale UFO: {exc}"
            return ""

    def _endpoint(self) -> tuple[str, int] | None:
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
            self._last_error = "Auto-start UFO disponibile solo per un server locale http://127.0.0.1/localhost."
            return None
        return parsed.hostname or "127.0.0.1", parsed.port or 5000

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._key:
            headers["X-API-Key"] = self._key
        return headers

    def _json(self, path: str, timeout: float = 2.0):
        req = Request(self.base_url + path, headers=self._headers(), method="GET")
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace") or "{}")

    def _healthy(self) -> bool:
        try:
            data = self._json("/api/health", timeout=1.5)
            return isinstance(data, dict) and str(data.get("status", "")).lower() in {"healthy", "ok", "success"}
        except (HTTPError, URLError, OSError, ValueError):
            return False

    def _client_online(self) -> bool:
        try:
            data = self._json("/api/clients", timeout=2.0)
        except Exception:
            return False
        candidates = []
        if isinstance(data, dict):
            for key in ("clients", "online_clients", "devices"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
                elif isinstance(value, dict):
                    candidates.extend(value.values())
        elif isinstance(data, list):
            candidates = data
        for item in candidates:
            if isinstance(item, str) and item == self.client_id:
                return True
            if isinstance(item, dict) and str(item.get("client_id") or item.get("id") or "") == self.client_id:
                return True
        return False

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    @staticmethod
    def _creationflags() -> int:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _spawn(self, args: list[str]) -> subprocess.Popen:
        if self._log_handle is None:
            self.ufo_dir.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self.log_path, "a", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            args,
            cwd=str(self.ufo_dir),
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=self._creationflags(),
        )

    @staticmethod
    def _terminate(proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return

        # On Windows the virtualenv launcher used by UFO starts the real
        # interpreter as a child process. Terminating only the launcher leaves
        # that child alive (and the UFO server keeps port 5000 open). Kill the
        # whole tree that belongs to the process JARVIS started.
        if sys.platform == "win32":
            try:
                completed = subprocess.run(
                    ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
                    timeout=8,
                    check=False,
                )
                if completed.returncode == 0:
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                    return
            except Exception:
                pass

        # Portable fallback.
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def start(self) -> bool:
        if not self.auto_start:
            return False
        if sys.platform != "win32":
            self._last_error = "UFO Windows sidecar disponibile solo su Windows."
            return False
        endpoint = self._endpoint()
        if endpoint is None:
            return False
        host, port = endpoint
        if not self.ufo_dir.exists() or not (self.ufo_dir / "ufo").exists():
            self._last_error = "Microsoft UFO non installato in external_integrations/UFO."
            return False
        if not self.python_exe.exists():
            self._last_error = "Ambiente Python UFO .ufo-env non trovato."
            return False
        if not (self.ufo_dir / "config" / "ufo" / "agents.yaml").exists():
            self._last_error = "config/ufo/agents.yaml non trovato."
            return False
        if not self._key:
            self._key = self._ensure_key()
        if not self._key:
            return False

        # Reuse a server that is already ours.  If the port is occupied but the
        # authenticated health check fails, don't kill or replace the process.
        if not self._healthy():
            if self._port_open(host, port):
                self._last_error = f"Porta UFO {port} occupata da un altro processo o da UFO con una chiave diversa."
                return False
            self._server = self._spawn([
                str(self.python_exe), "-m", "ufo.server.app",
                "--host", host,
                "--port", str(port),
                "--api-key", self._key,
                "--platform", "windows",
                "--log-level", "WARNING",
            ])
            self._started_server = True
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not self._healthy():
                if self._server.poll() is not None:
                    break
                time.sleep(0.25)
            if not self._healthy():
                self._last_error = f"Server UFO non diventato disponibile. Log: {self.log_path}"
                self.stop()
                return False

        if not self._client_online():
            ws_host = "127.0.0.1" if host in {"localhost", "::1"} else host
            ws_url = f"ws://{ws_host}:{port}/ws?token={quote(self._key, safe='')}"
            self._client = self._spawn([
                str(self.python_exe), "-m", "ufo.client.client",
                "--ws",
                "--ws-server", ws_url,
                "--client-id", self.client_id,
                "--platform", "windows",
                "--log-level", "WARNING",
            ])
            self._started_client = True
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not self._client_online():
                if self._client.poll() is not None:
                    break
                time.sleep(0.25)
            if not self._client_online():
                self._last_error = f"Client UFO {self.client_id} non registrato. Log: {self.log_path}"
                self.stop()
                return False

        self._last_error = ""
        return True

    def stop(self) -> None:
        if self._started_client:
            self._terminate(self._client)
        if self._started_server:
            self._terminate(self._server)
        self._client = None
        self._server = None
        self._started_client = False
        self._started_server = False
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def snapshot(self) -> dict:
        return {
            "enabled": self.auto_start,
            "healthy": self._healthy() if self._key else False,
            "client_online": self._client_online() if self._key else False,
            "base_url": self.base_url,
            "client_id": self.client_id,
            "started_server": self._started_server,
            "started_client": self._started_client,
            "error": self._last_error,
            "log": str(self.log_path),
        }
