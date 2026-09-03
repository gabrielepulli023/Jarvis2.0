import logging
import time

import psutil
from PySide6.QtCore import QThread, Signal

from settings_store import get_setting

LOGGER = logging.getLogger(__name__)


class ProactiveMonitorWorker(QThread):
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
