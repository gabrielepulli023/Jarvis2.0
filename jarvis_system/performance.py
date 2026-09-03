from __future__ import annotations
import gc
import os
import shutil
import subprocess
import threading
import time
from typing import Any
import psutil


class RuntimePerformanceMonitor:
    def __init__(self, voice=None, missions=None, automation=None):
        self.process = psutil.Process(os.getpid())
        self.voice = voice
        self.missions = missions
        self.automation = automation
        self._lock = threading.RLock()
        self._gpu_cache: dict[str, Any] = {"available": False}
        self._gpu_checked = 0.0

    def snapshot(self) -> dict:
        try:
            memory = self.process.memory_info()
            cpu = self.process.cpu_percent(None)
            threads = self.process.num_threads()
            handles = self.process.num_handles() if hasattr(self.process, "num_handles") else None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            memory = None
            cpu = None
            threads = None
            handles = None
        voice = self.voice.snapshot() if self.voice is not None else {}
        return {
            "cpu_percent": cpu,
            "rss_bytes": None if memory is None else memory.rss,
            "vms_bytes": None if memory is None else memory.vms,
            "threads": threads,
            "handles": handles,
            "queues": {
                "voice": voice.get("queued", 0),
                "active_missions": len(getattr(self.missions, "_tokens", ())) if self.missions is not None else 0,
            },
            "gpu": self.gpu(),
        }

    def gpu(self) -> dict:
        """Return cached vendor telemetry, or an explicit unavailable reason."""
        now = time.monotonic()
        with self._lock:
            if now - self._gpu_checked < 60:
                return dict(self._gpu_cache)
            self._gpu_checked = now
        executable = shutil.which("nvidia-smi")
        if not executable:
            value = {"available": False, "reason": "nvidia-smi unavailable"}
        else:
            try:
                result = subprocess.run(
                    [
                        executable,
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    shell=False,
                )
                rows = []
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        fields = [item.strip() for item in line.split(",")]
                        if len(fields) == 5:
                            rows.append(
                                {
                                    "name": fields[0],
                                    "utilization_percent": float(fields[1]),
                                    "memory_used_mb": float(fields[2]),
                                    "memory_total_mb": float(fields[3]),
                                    "temperature_c": float(fields[4]),
                                }
                            )
                value = {
                    "available": bool(rows),
                    "devices": rows,
                    "error": result.stderr[-500:] if result.returncode else "",
                }
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                value = {"available": False, "reason": type(exc).__name__}
        with self._lock:
            self._gpu_cache = value
        return dict(value)

    def system_pressure(self, limit: int = 10) -> dict:
        rows = []
        for process in psutil.process_iter(("pid", "name", "memory_percent", "cpu_percent")):
            try:
                rows.append(
                    {
                        "pid": process.info["pid"],
                        "name": str(process.info.get("name") or ""),
                        "memory_percent": round(float(process.info.get("memory_percent") or 0), 3),
                        "cpu_percent": round(float(process.info.get("cpu_percent") or 0), 2),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
                continue
        count = max(1, min(int(limit), 50))
        return {
            "success": True,
            "message": "Pressione di sistema analizzata.",
            "data": {
                "cpu_percent": psutil.cpu_percent(None),
                "memory": dict(psutil.virtual_memory()._asdict()),
                "top_memory_processes": sorted(rows, key=lambda row: row["memory_percent"], reverse=True)[:count],
                "top_cpu_processes": sorted(rows, key=lambda row: row["cpu_percent"], reverse=True)[:count],
            },
        }

    def optimize_own_memory(self) -> dict:
        before = self.process.memory_info().rss
        collected = gc.collect()
        trimmed = False
        if os.name == "nt":
            try:
                import ctypes

                trimmed = bool(ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess()))
            except (AttributeError, OSError):
                trimmed = False
        after = self.process.memory_info().rss
        return {
            "success": True,
            "message": "Memoria inutilizzata di JARVIS rilasciata quando supportato.",
            "data": {
                "scope": "jarvis_process_only",
                "rss_before": before,
                "rss_after": after,
                "python_objects_collected": collected,
                "working_set_trimmed": trimmed,
            },
        }
