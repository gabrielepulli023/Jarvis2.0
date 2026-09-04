import logging
import threading
import time

import psutil
from PySide6.QtCore import QThread, Signal

from settings_store import get_setting

LOGGER = logging.getLogger(__name__)


class SystemSignalMonitor:
    """Bounded sensor only: emits typed threshold-crossing events."""

    def __init__(self, events, interval: float = 30.0, probe=None):
        self.events = events
        self.interval = max(.5, float(interval))
        self.probe = probe or self._probe
        self._stop = threading.Event()
        self._thread = None
        self._states = {"memory": "normal", "disk": "normal", "battery": "normal"}
        self._initialized = False

    @staticmethod
    def _probe():
        battery = psutil.sensors_battery()
        return {
            "memory_percent": float(psutil.virtual_memory().percent),
            "disk_percent": float(psutil.disk_usage("C:\\").percent),
            "battery_percent": None if battery is None else float(battery.percent),
            "battery_plugged": None if battery is None else bool(battery.power_plugged),
        }

    def check_once(self):
        values = dict(self.probe() or {})
        rules = (("memory", "memory_percent", False), ("disk", "disk_percent", False), ("battery", "battery_percent", True))
        for metric, field, battery_rule in rules:
            value = values.get(field)
            if metric == "battery" and values.get("battery_plugged") is not False:
                severity = "normal"
            elif value is None:
                severity = "normal"
            elif battery_rule:
                severity = "critical" if value <= 5 else "warning" if value <= 15 else "normal"
            else:
                severity = "critical" if value >= 97 else "warning" if value >= 90 else "normal"
            previous = self._states[metric]
            if metric == "battery" and values.get("battery_plugged") is True:
                self._states[metric] = "normal"
                continue
            if previous == "warning" and severity == "normal":
                clear = 17 if battery_rule else 88
                if (battery_rule and value is not None and value < clear) or (not battery_rule and value is not None and value > clear):
                    severity = previous
            if previous == "critical" and severity != "critical":
                clear = 7 if battery_rule else 95
                if (battery_rule and value is not None and value < clear) or (not battery_rule and value is not None and value > clear):
                    severity = previous
            if self._initialized and severity != previous and severity != "normal" and previous != "critical":
                suffix = "_critical" if severity == "critical" else "_pressure" if metric != "battery" else "_low"
                self.events.publish(f"system.{metric}{suffix}", {"metric": field, "value": round(float(value), 1)}, source="system_signals", confidence=1.0)
            elif not self._initialized and severity != "normal":
                suffix = "_critical" if severity == "critical" else "_pressure" if metric != "battery" else "_low"
                self.events.publish(f"system.{metric}{suffix}", {"metric": field, "value": round(float(value), 1)}, source="system_signals", confidence=1.0)
            self._states[metric] = severity
        self._initialized = True
        return values

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        try:
            self.check_once()
        except Exception as exc:
            self.events.publish("hardware.monitor_failed", {"monitor": "system_signals", "error": type(exc).__name__}, source="system_signals")
        self._thread = threading.Thread(target=self._run, name="jarvis-system-signals", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.check_once()
            except Exception as exc:
                self.events.publish("hardware.monitor_failed", {"monitor": "system_signals", "error": type(exc).__name__}, source="system_signals")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def restart(self):
        self.stop()
        self._initialized = False
        self._states = {"memory": "normal", "disk": "normal", "battery": "normal"}
        self.start()
        return self.healthy()

    def healthy(self):
        return bool(self._thread and self._thread.is_alive())


class ProactiveMonitorWorker(QThread):
    """Deprecated compatibility adapter; never owns canonical decisions."""
    alert = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last = {}
        self._last_error_at = 0.0

    def stop(self):
        self._running = False

    def _emit_once(self, key, message, cooldown=1800):
        now = time.time()
        if now - self._last.get(key, 0) >= cooldown:
            self._last[key] = now
            self.alert.emit(message)

    def _report_error(self, exc):
        now = time.time()
        if now - self._last_error_at >= 1800:
            self._last_error_at = now
            LOGGER.warning("Monitor proattivo degradato: %s", type(exc).__name__)

    def run(self):
        while self._running:
            if get_setting("proactive_enabled", True):
                try:
                    disk = psutil.disk_usage("C:\\")
                    if disk.percent >= float(get_setting("disk_alert_percent", 90)):
                        self._emit_once("disk", f"Attenzione: il disco C è occupato al {disk.percent:.0f} percento.")
                    battery = psutil.sensors_battery()
                    if battery and not battery.power_plugged and battery.percent <= 15:
                        self._emit_once("battery", f"Batteria al {battery.percent:.0f} percento. Collega l'alimentazione.", 900)
                    memory = psutil.virtual_memory()
                    if memory.percent >= 95:
                        self._emit_once("memory", f"Memoria RAM utilizzata al {memory.percent:.0f} percento.", 900)
                except Exception as exc:
                    self._report_error(exc)
            for _ in range(120):
                if not self._running:
                    return
                self.msleep(500)
