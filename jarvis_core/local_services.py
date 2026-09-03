from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from settings_store import get_setting


@dataclass(slots=True)
class LocalService:
    name: str
    url: str
    state: str = "stopped"
    ownership: str = "none"
    process_id: str | None = None
    pid: int | None = None
    error: str = ""
    container_id: str | None = None


class LocalServicesManager:
    """Lifecycle for local sidecars, including the Dockerized OpenHands app.

    A listening port is never enough to claim a service: readiness probes identify
    the protocol and only processes spawned through ProcessManager are owned.
    """

    def __init__(self, processes, logger=None, *, request: Callable | None = None):
        self.processes = processes
        self.logger = logger
        self._request = request or self._http_json
        self._lock = threading.RLock()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self.services = {
            "screenpipe": LocalService("screenpipe", self._screenpipe_url()),
            "llama_cpp": LocalService("llama.cpp", self._llama_url()),
            "openhands": LocalService("OpenHands", self._openhands_url()),
        }
        self._output: dict[str, deque[str]] = {name: deque(maxlen=80) for name in self.services}
        self._reader_threads: list[threading.Thread] = []

    @staticmethod
    def _http_json(url: str, headers: dict[str, str] | None = None, timeout: float = 2.5) -> Any:
        request = Request(url, headers={"Accept": "application/json", **(headers or {})}, method="GET")
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace") or "{}")

    @staticmethod
    def _secret() -> str:
        try:
            import keyring
            return str(keyring.get_password("jarvis.screenpipe", "api_key") or "")
        except Exception:
            return ""

    @staticmethod
    def _base(value: Any, default: str) -> str:
        return str(value or default).rstrip("/")

    def _screenpipe_url(self) -> str:
        return self._base(get_setting("screenpipe_url", "http://127.0.0.1:3030"), "http://127.0.0.1:3030")

    def _llama_url(self) -> str:
        host = str(get_setting("llama_cpp_host", "127.0.0.1") or "127.0.0.1")
        port = int(get_setting("llama_cpp_port", 8080) or 8080)
        return self._base(get_setting("llamacpp_url", f"http://{host}:{port}"), f"http://{host}:{port}")

    def _openhands_url(self) -> str:
        return self._base(get_setting("openhands_url", "http://127.0.0.1:3000"), "http://127.0.0.1:3000")

    def _log(self, level: str, event: str, **extra: Any) -> None:
        if self.logger is not None:
            getattr(self.logger, level, self.logger.info)(event, extra=extra)

    def _screenpipe_probe(self) -> bool:
        token = self._secret()
        headers = {"Authorization": f"Bearer {token}", "X-API-Key": token} if token else {}
        try:
            value = self._request(self.services["screenpipe"].url + "/search?limit=1&content_type=all", headers)
            return isinstance(value, (dict, list))
        except (HTTPError, URLError, OSError, ValueError):
            return False

    def _llama_probe(self) -> bool:
        try:
            value = self._request(self.services["llama_cpp"].url + "/v1/models")
            rows = value.get("data", []) if isinstance(value, dict) else []
            return isinstance(rows, list) and bool(rows) and all(isinstance(row, dict) for row in rows)
        except (HTTPError, URLError, OSError, ValueError):
            return False

    def _openhands_probe(self) -> bool:
        """Accept the real OpenHands HTTP app, without logging its response."""
        try:
            request = Request(self.services["openhands"].url, headers={"Accept": "text/html,application/json"})
            with urlopen(request, timeout=2.5) as response:
                return 200 <= int(response.status) < 400 and bool(response.read(256))
        except (HTTPError, URLError, OSError, ValueError):
            return False

    def _ready(self, name: str) -> bool:
        if name == "screenpipe":
            return self._screenpipe_probe()
        if name == "llama_cpp":
            return self._llama_probe()
        return self._openhands_probe()

    def _command(self, name: str) -> tuple[str, ...] | None:
        if name == "llama_cpp":
            executable = str(get_setting("llama_cpp_executable", "") or "").strip() or shutil.which("llama-server")
            if not executable:
                return None
            model = str(get_setting("llama_cpp_model", "bartowski/Qwen2.5-3B-Instruct-GGUF:Q4_K_M") or "").strip()
            host = str(get_setting("llama_cpp_host", "127.0.0.1") or "127.0.0.1")
            port = str(int(get_setting("llama_cpp_port", 8080) or 8080))
            return (executable, "-hf", model, "--host", host, "--port", port)
        if name == "openhands":
            wsl = shutil.which("wsl.exe")
            if not wsl:
                return None
            return (wsl, "-d", str(get_setting("openhands_wsl_distro", "Ubuntu") or "Ubuntu"), "--", "docker", "start", "openhands-jarvis")
        executable = shutil.which("screenpipe")
        if executable:
            return (executable, "record")
        npx = shutil.which("npx")
        return (npx, "--no-install", "screenpipe", "record") if npx else None

    def _wsl_home(self) -> str:
        wsl = shutil.which("wsl.exe")
        if not wsl:
            return ""
        try:
            result = subprocess.run((wsl, "-d", str(get_setting("openhands_wsl_distro", "Ubuntu") or "Ubuntu"), "--", "printenv", "HOME"),
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
                                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)), check=False)
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def _docker(self, args: tuple[str, ...], timeout: float = 15.0) -> tuple[int, str, str]:
        wsl = shutil.which("wsl.exe")
        if not wsl:
            return 127, "", "wsl.exe not found"
        resolved = tuple(self._wsl_home() + "/.openhands:/.openhands" if arg == "~/.openhands:/.openhands" and self._wsl_home() else arg for arg in args)
        command = (wsl, "-d", str(get_setting("openhands_wsl_distro", "Ubuntu") or "Ubuntu"), "--", "docker", *resolved)
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                    creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)), check=False)
            return result.returncode, result.stdout[-2000:], result.stderr[-2000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", str(exc)

    def _openhands_container(self) -> tuple[bool, bool, bool]:
        code, out, _ = self._docker(("inspect", "--format", "{{.State.Status}}|{{index .Config.Labels \"com.jarvis.owner\"}}", "openhands-jarvis"))
        if code != 0:
            return False, False, False
        status, _, owner = (out.strip() + "||").partition("|")
        return True, status == "running", owner.strip() == "jarvis"

    def _start_openhands(self) -> None:
        service = self.services["openhands"]
        exists, running, _previously_owned = self._openhands_container()
        if running and self._openhands_probe():
            service.state, service.ownership, service.error = "ready", "external", ""
            self._log("info", "openhands.already_running", ownership="external")
            return
        if running:
            service.state, service.ownership, service.error = "failed", "external", "container running but HTTP readiness failed"
            self._log("warning", "openhands.failed", error=service.error)
            return
        if not bool(get_setting("openhands_enabled", True)) or not bool(get_setting("openhands_autostart", True)):
            service.state, service.ownership = "disabled", "none"
            return
        service.state = "starting"
        if exists:
            code, _, err = self._docker(("start", "openhands-jarvis"))
            # A stopped container becomes owned by this session when this
            # session explicitly starts it; persistent labels are not session
            # ownership.
            owner = "jarvis" if code == 0 else "none"
        else:
            owner = "jarvis"
            code, _, err = self._docker((
                "run", "-d", "--name", "openhands-jarvis", "--restart=no",
                "--label", "com.jarvis.owner=jarvis", "--label", "com.jarvis.service=openhands",
                "-e", "AGENT_SERVER_IMAGE_REPOSITORY=ghcr.io/openhands/agent-server",
                "-e", "AGENT_SERVER_IMAGE_TAG=1.26.0-python", "-e", "LOG_ALL_EVENTS=true",
                "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", "~/.openhands:/.openhands",
                "-p", "127.0.0.1:3000:3000", "--add-host", "host.docker.internal:host-gateway",
                "ghcr.io/openhands/openhands:1.8.0"))
        if code != 0:
            service.state, service.ownership, service.error = "failed", "none", "Docker/WSL unavailable or container start failed"
            self._log("warning", "openhands.failed", error=service.error)
            return
        service.ownership = owner
        timeout = max(5.0, min(180.0, float(get_setting("openhands_startup_timeout", 60.0) or 60.0)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stopping:
            if self._openhands_probe():
                service.state = "ready"
                self._log("info", "openhands.ready", ownership=owner)
                return
            time.sleep(0.5)
        service.state, service.error = "failed", "readiness timeout"
        self._log("warning", "openhands.failed", error=service.error)
        if owner == "jarvis":
            self._docker(("stop", "openhands-jarvis"), timeout=10.0)

    def _capture(self, name: str, stream) -> None:
        try:
            for line in iter(stream.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self._output[name].append(text[:500])
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _start_one(self, name: str) -> None:
        if name == "openhands":
            self._start_openhands()
            return
        service = self.services[name]
        if self._ready(name):
            service.state, service.ownership, service.error = "ready", "external", ""
            self._log("info", f"{name}.already_running", ownership="external")
            return
        if not bool(get_setting(f"{name}_enabled", True)) or not bool(get_setting(f"{name}_autostart", True)):
            service.state, service.ownership = "disabled", "none"
            return
        command = self._command(name)
        if not command:
            service.state, service.ownership, service.error = "failed", "none", "executable not found"
            self._log("warning", f"{name}.failed", error=service.error)
            return
        service.state, service.error = "starting", ""
        self._log("info", f"{name}.starting")
        try:
            item = self.processes.start(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
            service.process_id, service.pid, service.ownership = item.id, item.process.pid, "jarvis"
            thread = threading.Thread(target=self._capture, args=(name, item.process.stdout), daemon=True,
                                       name=f"jarvis-{name}-output")
            thread.start(); self._reader_threads.append(thread)
        except (OSError, ValueError) as exc:
            service.state, service.ownership, service.error = "failed", "none", str(exc)
            self._log("warning", f"{name}.failed", error=service.error)
            return
        timeout = max(1.0, min(180.0, float(get_setting(f"{name}_startup_timeout", 30.0) or 30.0)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stopping:
            if self._ready(name):
                service.state = "ready"
                self._log("info", f"{name}.ready", ownership="jarvis", pid=service.pid)
                return
            proc = self.processes.snapshot()
            if not any(row["id"] == service.process_id and row["running"] for row in proc):
                break
            time.sleep(0.25)
        service.state, service.error = "failed", f"readiness timeout; diagnostic lines={len(self._output[name])}"
        self._log("warning", f"{name}.failed", error=service.error)
        self._stop_one(name)

    def start(self) -> None:
        self._stopping = False
        for name in ("screenpipe", "llama_cpp", "openhands"):
            try:
                self._start_one(name)
            except Exception as exc:
                self.services[name].state = "failed"
                self.services[name].error = str(exc)
                self._log("warning", f"{name}.failed", error=str(exc))

    def start_background(self) -> None:
        """Start sidecars off the critical UI/voice startup path."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self.start, name="jarvis-local-services", daemon=True)
            self._thread.start()

    def _stop_one(self, name: str) -> None:
        service = self.services[name]
        if name == "openhands":
            if service.ownership == "jarvis":
                self._docker(("stop", "openhands-jarvis"), timeout=10.0)
                service.state, service.ownership = "stopped", "none"
                self._log("info", "openhands.stopped")
            return
        if service.ownership != "jarvis" or not service.process_id:
            return
        try:
            self.processes.kill_tree(service.process_id, timeout=3.0)
        finally:
            service.state, service.ownership, service.process_id, service.pid = "stopped", "none", None, None
            self._log("info", f"{name}.stopped")

    def stop(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5.0)
            for name in ("screenpipe", "llama_cpp", "openhands"):
                try:
                    self._stop_one(name)
                except Exception as exc:
                    self._log("warning", f"{name}.stop_failed", error=str(exc))

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: {"url": item.url, "state": item.state, "ownership": item.ownership,
                       "pid": item.pid, "container_id": item.container_id, "error": item.error} for name, item in self.services.items()}

    def wait_ready(self, name: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if self.services.get(name) and self._ready(name):
                self.services[name].state = "ready"
                return True
            time.sleep(0.1)
        return False
