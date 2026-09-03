from __future__ import annotations

import hashlib
import io
import threading
import time
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageChops, ImageStat


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    jpeg: bytes
    region: tuple[int, int, int, int]
    source: str
    captured_at: float
    fingerprint: str
    changed_ratio: float


class ScreenCaptureEngine:
    """Volatile screen capture with regional targets and adaptive diffing."""

    def __init__(self, grabber: Callable[..., Image.Image] | None = None):
        self._grabber = grabber or self._default_grabber
        self._previous: Image.Image | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _default_grabber(*, region=None):
        import pyautogui

        return pyautogui.screenshot(region=region)

    def full(self) -> CaptureFrame:
        return self._capture(None, "full")

    def region(self, x: int, y: int, width: int, height: int) -> CaptureFrame:
        if width <= 0 or height <= 0:
            raise ValueError("Regione non valida")
        return self._capture((int(x), int(y), int(width), int(height)), "region")

    def active_window(self, window_manager) -> CaptureFrame:
        window = window_manager.active()
        if window is None:
            raise RuntimeError("Nessuna finestra attiva")
        return self._capture((window.x, window.y, window.width, window.height), "active_window")

    def monitor(self, window_manager, monitor_index: int) -> CaptureFrame:
        areas = window_manager.backend.work_areas()
        if not 0 <= int(monitor_index) < len(areas):
            raise ValueError("Monitor non valido")
        left, top, right, bottom = areas[int(monitor_index)]
        return self._capture((left, top, right - left, bottom - top), f"monitor:{monitor_index}")

    def _capture(self, region, source: str) -> CaptureFrame:
        image = self._grabber(region=region).convert("RGB")
        actual = region or (0, 0, image.width, image.height)
        with self._lock:
            previous = self._previous
            changed = (
                self._changed_ratio(previous, image) if previous is not None and previous.size == image.size else 1.0
            )
            self._previous = image.copy()
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=82, optimize=True)
        payload = buffer.getvalue()
        return CaptureFrame(payload, actual, source, time.time(), hashlib.sha256(payload).hexdigest(), changed)

    @staticmethod
    def _changed_ratio(previous: Image.Image, current: Image.Image) -> float:
        difference = ImageChops.difference(previous, current)
        mean = sum(ImageStat.Stat(difference).mean) / (255.0 * 3.0)
        return round(max(0.0, min(1.0, mean)), 6)

    def clear(self) -> None:
        with self._lock:
            self._previous = None
