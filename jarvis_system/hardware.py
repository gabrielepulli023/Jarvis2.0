from __future__ import annotations
import platform
import threading
import time
from dataclasses import asdict
from typing import Any
import psutil


class SystemInformation:
    def __init__(self, windows=None, gpu_probe=None):
        self.windows = windows
        self.gpu_probe = gpu_probe

    def snapshot(self) -> dict:
        memory = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        temperatures = {}
        try:
            temperatures = {
                name: [asdict(item) for item in rows] for name, rows in psutil.sensors_temperatures().items()
            }
        except (AttributeError, OSError):
            pass
        disks = []
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            disks.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "filesystem": partition.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )
        monitors = []
        if self.windows is not None:
            try:
                for index, (left, top, right, bottom) in enumerate(self.windows.backend.work_areas()):
                    monitors.append(
                        {
                            "monitor_id": index,
                            "x": left,
                            "y": top,
                            "width": right - left,
                            "height": bottom - top,
                            "primary": index == 0,
                        }
                    )
            except OSError:
                pass
        audio = []
        try:
            import sounddevice

            for index, row in enumerate(sounddevice.query_devices()):
                audio.append(
                    {
                        "id": index,
                        "name": str(row["name"]),
                        "inputs": int(row["max_input_channels"]),
                        "outputs": int(row["max_output_channels"]),
                        "sample_rate": float(row["default_samplerate"]),
                    }
                )
        except Exception:
            pass
        return {
            "platform": platform.platform(),
            "windows_version": platform.version(),
            "hostname": platform.node(),
            "boot_time": psutil.boot_time(),
            "uptime_seconds": max(0, time.time() - psutil.boot_time()),
            "cpu": {
                "logical": psutil.cpu_count(),
                "physical": psutil.cpu_count(logical=False),
                "percent": psutil.cpu_percent(None),
                "frequency_mhz": None if psutil.cpu_freq() is None else psutil.cpu_freq().current,
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent,
            },
            "storage": disks,
            "battery": (
                None
                if battery is None
                else {"percent": battery.percent, "plugged": battery.power_plugged, "seconds_left": battery.secsleft}
            ),
            "temperatures": temperatures,
            "monitors": monitors,
            "audio_devices": audio,
            "gpu": (
                self.gpu_probe() if self.gpu_probe is not None else {"available": False, "reason": "probe unavailable"}
            ),
        }


class HardwareEventMonitor:
    """Low-frequency hardware/network diff monitor; payloads contain metadata only."""

    def __init__(self, events, probe=None, interval: float = 3):
        self.events = events
        self.probe = probe or self._probe
        self.interval = max(0.2, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous: dict[str, Any] | None = None

    @staticmethod
    def _probe() -> dict:
        disks = sorted((row.device, row.mountpoint) for row in psutil.disk_partitions(all=False))
        network = {name: state.isup for name, state in psutil.net_if_stats().items()}
        audio = []
        try:
            import sounddevice

            audio = sorted(
                (str(row["name"]), int(row["max_input_channels"]), int(row["max_output_channels"]))
                for row in sounddevice.query_devices()
            )
        except Exception:
            pass
        monitors: int | None = None
        if __import__("os").name == "nt":
            try:
                monitors = int(__import__("ctypes").windll.user32.GetSystemMetrics(80))
            except (AttributeError, OSError):
                pass
        return {"devices": disks, "network": network, "audio": audio, "monitors": monitors}

    def check_once(self) -> dict:
        current = dict(self.probe() or {})
        previous = self._previous
        self._previous = current
        if previous is not None and current != previous:
            before_devices = set(map(tuple, previous.get("devices", ())))
            after_devices = set(map(tuple, current.get("devices", ())))
            for row in sorted(after_devices - before_devices):
                self.events.publish("device.connected", {"device": row[0], "mountpoint": row[1]}, source="hardware")
            for row in sorted(before_devices - after_devices):
                self.events.publish("device.disconnected", {"device": row[0], "mountpoint": row[1]}, source="hardware")
            if current.get("network") != previous.get("network"):
                self.events.publish("network.changed", {"interfaces": current.get("network", {})}, source="hardware")
            if current.get("audio") != previous.get("audio"):
                self.events.publish("audio_devices.changed", {"devices": current.get("audio", [])}, source="hardware")
            if current.get("monitors") != previous.get("monitors"):
                self.events.publish("monitors.changed", {"count": current.get("monitors")}, source="hardware")
        return current

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.check_once()
        thread = threading.Thread(target=self._run, name="jarvis-hardware-events", daemon=True)
        self._thread = thread
        thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.check_once()
            except Exception as exc:
                self.events.publish("hardware.monitor_failed", {"error": type(exc).__name__}, source="hardware")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def healthy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def restart(self) -> bool:
        self.stop()
        self.start()
        return self.healthy()
