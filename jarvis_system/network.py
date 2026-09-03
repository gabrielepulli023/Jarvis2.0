from __future__ import annotations
import ipaddress
import re
import socket
import subprocess
import time
import psutil
from jarvis_core.logging import redact


class NetworkAgent:
    _HOST = re.compile(
        r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$|^localhost$"
    )

    def adapters(self) -> list[dict]:
        stats = psutil.net_if_stats()
        rows = []
        for name, addresses in psutil.net_if_addrs().items():
            state = stats.get(name)
            rows.append(
                {
                    "name": name,
                    "up": bool(state and state.isup),
                    "speed_mbps": None if state is None else state.speed,
                    "mtu": None if state is None else state.mtu,
                    "addresses": [
                        {"family": str(item.family), "address": item.address, "netmask": item.netmask}
                        for item in addresses
                    ],
                }
            )
        return rows

    def connectivity(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2) -> dict:
        started = time.monotonic()
        try:
            with socket.create_connection((str(host), int(port)), timeout=max(0.1, min(float(timeout), 10))):
                pass
            return {
                "success": True,
                "host": str(host),
                "port": int(port),
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        except OSError as exc:
            return {
                "success": False,
                "host": str(host),
                "port": int(port),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": type(exc).__name__,
            }

    def dns(self, hostname: str) -> dict:
        self._validate_host(hostname)
        try:
            return {
                "success": True,
                "hostname": hostname,
                "addresses": sorted({row[4][0] for row in socket.getaddrinfo(hostname, None)}),
            }
        except OSError as exc:
            return {"success": False, "hostname": hostname, "error": redact(str(exc))}

    def ping(self, host: str, timeout: float = 3) -> dict:
        self._validate_host(host)
        milliseconds = max(100, min(int(float(timeout) * 1000), 10000))
        command = ["ping", "-n", "1", "-w", str(milliseconds), host]
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=float(timeout) + 1, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "error": type(exc).__name__}
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "output": result.stdout[-4000:],
        }

    @classmethod
    def _validate_host(cls, host: str) -> None:
        value = str(host).strip()
        try:
            ipaddress.ip_address(value)
            return
        except ValueError:
            pass
        if not cls._HOST.fullmatch(value):
            raise ValueError("Host non valido")
