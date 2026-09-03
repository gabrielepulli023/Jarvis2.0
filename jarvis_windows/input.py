from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable

import pyautogui


class InputController:
    """Validated desktop input over PyAutoGUI's native Windows backend."""

    BUTTONS = frozenset({"left", "middle", "right"})

    def __init__(self, backend=pyautogui, bounds: Callable[[], tuple[int, int, int, int]] | None = None):
        self.backend = backend
        self._bounds = bounds or self._virtual_bounds
        self._held: set[str] = set()
        self._lock = threading.RLock()

    @staticmethod
    def _virtual_bounds() -> tuple[int, int, int, int]:
        if hasattr(ctypes, "windll"):
            user32 = ctypes.windll.user32
            return (
                int(user32.GetSystemMetrics(76)),
                int(user32.GetSystemMetrics(77)),
                int(user32.GetSystemMetrics(78)),
                int(user32.GetSystemMetrics(79)),
            )
        width, height = pyautogui.size()
        return 0, 0, int(width), int(height)

    def _point(self, x: int | float, y: int | float) -> tuple[int, int]:
        px, py = int(x), int(y)
        left, top, width, height = self._bounds()
        if width <= 0 or height <= 0 or not (left <= px < left + width and top <= py < top + height):
            raise ValueError("Coordinate fuori dallo schermo virtuale.")
        return px, py

    def _button(self, button: str) -> str:
        value = str(button).casefold().strip()
        if value not in self.BUTTONS:
            raise ValueError("Pulsante mouse non supportato.")
        return value

    def _key(self, key: str) -> str:
        value = str(key).casefold().strip()
        if value not in set(self.backend.KEYBOARD_KEYS):
            raise ValueError(f"Tasto non supportato: {value}")
        return value

    @staticmethod
    def _duration(value: float) -> float:
        return max(0.0, min(float(value), 5.0))

    def move_absolute(self, x: int, y: int, duration: float = 0.15) -> dict:
        px, py = self._point(x, y)
        self.backend.moveTo(px, py, duration=self._duration(duration))
        return {"success": True, "message": "Mouse spostato.", "data": {"x": px, "y": py}}

    def move_relative(self, dx: int, dy: int, duration: float = 0.15) -> dict:
        current = self.backend.position()
        px, py = self._point(int(current.x) + int(dx), int(current.y) + int(dy))
        self.backend.moveTo(px, py, duration=self._duration(duration))
        return {"success": True, "message": "Mouse spostato relativamente.", "data": {"x": px, "y": py}}

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> dict:
        count = int(clicks)
        if not 1 <= count <= 3:
            raise ValueError("Numero click fuori limite.")
        kwargs = {"button": self._button(button), "clicks": count, "interval": 0.12}
        if x is not None or y is not None:
            if x is None or y is None:
                raise ValueError("Servono entrambe le coordinate.")
            kwargs["x"], kwargs["y"] = self._point(x, y)
        self.backend.click(**kwargs)
        return {"success": True, "message": "Click eseguito."}

    def drag(self, x: int, y: int, button: str = "left", duration: float = 0.4) -> dict:
        px, py = self._point(x, y)
        self.backend.dragTo(px, py, duration=self._duration(duration), button=self._button(button))
        return {"success": True, "message": "Trascinamento eseguito.", "data": {"x": px, "y": py}}

    def scroll(self, amount: int) -> dict:
        value = max(-100, min(int(amount), 100))
        self.backend.scroll(value)
        return {"success": True, "message": "Scroll eseguito.", "data": {"amount": value}}

    def press(self, key: str, presses: int = 1) -> dict:
        count = max(1, min(int(presses), 20))
        self.backend.press(self._key(key), presses=count, interval=0.05)
        return {"success": True, "message": "Tasto premuto.", "data": {"presses": count}}

    def write(self, text: str, interval: float = 0.01) -> dict:
        value = str(text)
        if len(value) > 10_000:
            raise ValueError("Testo troppo lungo per l'inserimento desktop.")
        self.backend.write(value, interval=max(0.0, min(float(interval), 0.25)))
        return {"success": True, "message": "Testo inserito.", "data": {"characters": len(value)}}

    def hotkey(self, keys: list[str] | tuple[str, ...]) -> dict:
        values = tuple(self._key(key) for key in keys)
        if not 2 <= len(values) <= 5:
            raise ValueError("Una scorciatoia richiede da 2 a 5 tasti.")
        self.backend.hotkey(*values)
        return {"success": True, "message": "Scorciatoia eseguita.", "data": {"keys": values}}

    def key_down(self, key: str) -> dict:
        value = self._key(key)
        with self._lock:
            self.backend.keyDown(value)
            self._held.add(value)
        return {"success": True, "message": "Tasto mantenuto premuto.", "data": {"key": value}}

    def key_up(self, key: str) -> dict:
        value = self._key(key)
        with self._lock:
            self.backend.keyUp(value)
            self._held.discard(value)
        return {"success": True, "message": "Tasto rilasciato.", "data": {"key": value}}

    def release_all(self) -> None:
        with self._lock:
            for key in tuple(self._held):
                self.backend.keyUp(key)
            self._held.clear()
