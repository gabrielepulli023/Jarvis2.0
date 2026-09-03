from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .client import BrokerClient


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    executable: str
    parameters: str
    working_directory: str


def build_launch_spec(address: str | None = None, tcp_port: int | None = None) -> LaunchSpec:
    executable = str(Path(sys.executable).resolve())
    arguments = ["--broker"] if getattr(sys, "frozen", False) else ["-m", "jarvis_broker.server"]
    if address:
        arguments += ["--broker-address", address] if getattr(sys, "frozen", False) else ["--address", address]
    if tcp_port is not None:
        option = "--broker-tcp-port" if getattr(sys, "frozen", False) else "--tcp-port"
        arguments += [option, str(int(tcp_port))]
    return LaunchSpec(executable, subprocess.list2cmdline(arguments), str(Path(__file__).resolve().parent.parent))


class BrokerManager:
    """Controls the separately elevated broker without elevating JARVIS itself."""

    def __init__(self, client: BrokerClient | None = None):
        self.client = client or BrokerClient(address=("127.0.0.1", 1), family="AF_INET")
        self._has_endpoint = client is not None
        self._last_launch = 0.0

    def health(self) -> bool:
        if not self._has_endpoint:
            return False
        return self.client.execute("broker.ping", {}).success

    def start_elevated(self) -> bool:
        if os.name != "nt":
            return False
        if self.health():
            return True
        now = time.monotonic()
        if now - self._last_launch < 10.0:
            return False
        self._last_launch = now
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        self.client.address = ("127.0.0.1", port)
        self.client.family = "AF_INET"
        spec = build_launch_spec(tcp_port=port)
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", spec.executable, spec.parameters, spec.working_directory, 0
        )
        self._has_endpoint = int(result) > 32
        return self._has_endpoint

    def ensure_available(self, timeout: float = 15.0) -> bool:
        if self.health():
            return True
        if not self.start_elevated():
            return False
        deadline = time.monotonic() + max(0.5, min(float(timeout), 60))
        while time.monotonic() < deadline:
            if self.health():
                return True
            time.sleep(0.2)
        return False

    @staticmethod
    def diagnostics() -> dict:
        from app_paths import data_path

        path = data_path("acceptance") / "broker-startup.json"
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {"stage": "no_diagnostics"}

    def stop(self, *, confirmed: bool) -> bool:
        return self.client.execute("broker.stop", {}, confirmed=confirmed).success
