from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time
from dataclasses import asdict, dataclass
from typing import List, Protocol


@dataclass(frozen=True, slots=True)
class WindowInfo:
    handle: int
    title: str
    pid: int
    executable: str | None
    x: int
    y: int
    width: int
    height: int
    monitor: int
    state: str
    active: bool


class WindowBackend(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...
    def show(self, handle: int, command: int) -> bool: ...
    def close(self, handle: int) -> bool: ...
    def focus(self, handle: int) -> bool: ...
    def move(self, handle: int, x: int, y: int, width: int, height: int) -> bool: ...
    def work_areas(self) -> list[tuple[int, int, int, int]]: ...


class NativeWindowBackend:
    SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9

    def __init__(self):
        if os.name != "nt":
            raise OSError("WindowManager richiede Windows")
        self.user32 = ctypes.windll.user32

    def list_windows(self) -> list[WindowInfo]:
        import psutil

        rows: list[WindowInfo] = []
        active = int(self.user32.GetForegroundWindow())
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def collect(hwnd, _lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, title, length + 1)
            rect = ctypes.wintypes.RECT()
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                executable = psutil.Process(pid.value).exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                executable = None
            placement = ctypes.create_string_buffer(44)
            ctypes.cast(placement, ctypes.POINTER(ctypes.c_uint))[0] = 44
            state = "normal"
            if self.user32.IsIconic(hwnd):
                state = "minimized"
            elif self.user32.IsZoomed(hwnd):
                state = "maximized"
            monitor = int(self.user32.MonitorFromWindow(hwnd, 2))
            rows.append(
                WindowInfo(
                    int(hwnd),
                    title.value,
                    int(pid.value),
                    executable,
                    rect.left,
                    rect.top,
                    rect.right - rect.left,
                    rect.bottom - rect.top,
                    monitor,
                    state,
                    int(hwnd) == active,
                )
            )
            return True

        self.user32.EnumWindows(callback_type(collect), 0)
        return rows

    def show(self, handle: int, command: int) -> bool:
        return bool(self.user32.ShowWindow(handle, command) or self.user32.IsWindow(handle))

    def close(self, handle: int) -> bool:
        return bool(self.user32.PostMessageW(handle, 0x0010, 0, 0))

    def focus(self, handle: int) -> bool:
        handle = int(handle)
        if not self.user32.IsWindow(handle):
            return False
        self.user32.ShowWindow(handle, self.SW_RESTORE)
        self.user32.BringWindowToTop(handle)
        # Windows may deny foreground changes across input queues.  The
        # documented user-input handoff (ALT) permits a normal foreground
        # request without changing system policy or registry settings.
        self.user32.AllowSetForegroundWindow(-1)
        self.user32.keybd_event(0x12, 0, 0, 0)
        self.user32.keybd_event(0x12, 0, 2, 0)
        requested = bool(self.user32.SetForegroundWindow(handle))
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            foreground = int(self.user32.GetForegroundWindow())
            root = int(self.user32.GetAncestor(handle, 2)) or handle
            foreground_root = int(self.user32.GetAncestor(foreground, 2)) if foreground else 0
            if foreground in {handle, root} or foreground_root == root:
                return True
            time.sleep(0.01)
        return requested and int(self.user32.GetForegroundWindow()) == handle

    def move(self, handle: int, x: int, y: int, width: int, height: int) -> bool:
        return bool(self.user32.MoveWindow(handle, x, y, width, height, True))

    def work_areas(self) -> list[tuple[int, int, int, int]]:
        import ctypes.wintypes

        areas: list[tuple[int, int, int, int]] = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double
        )

        def collect(_monitor, _hdc, rect, _data):
            value = rect.contents
            areas.append((value.left, value.top, value.right, value.bottom))
            return 1

        self.user32.EnumDisplayMonitors(0, 0, callback_type(collect), 0)
        return sorted(areas, key=lambda row: (row[0], row[1]))


class WindowManager:
    def __init__(self, backend: WindowBackend | None = None):
        self.backend = backend or NativeWindowBackend()

    def list(self) -> List[dict]:
        return [asdict(item) for item in self.backend.list_windows()]

    def active(self) -> WindowInfo | None:
        return next((item for item in self.backend.list_windows() if item.active), None)

    def find(self, query: str) -> List[WindowInfo]:
        needle = str(query).strip().casefold()
        return [
            item
            for item in self.backend.list_windows()
            if needle in item.title.casefold() or (item.executable and needle in item.executable.casefold())
        ]

    def _one(self, query: str) -> WindowInfo:
        matches = self.find(query)
        if not matches:
            raise LookupError(f"Finestra non trovata: {query}")
        if len(matches) > 1:
            exact = [item for item in matches if item.title.casefold() == query.casefold()]
            if len(exact) == 1:
                return exact[0]
        return matches[0]

    def minimize(self, query: str) -> bool:
        return self.backend.show(self._one(query).handle, 6)

    def maximize(self, query: str) -> bool:
        return self.backend.show(self._one(query).handle, 3)

    def restore(self, query: str) -> bool:
        return self.backend.show(self._one(query).handle, 9)

    def close(self, query: str) -> bool:
        return self.backend.close(self._one(query).handle)

    def focus(self, query: str) -> bool:
        return self.backend.focus(self._one(query).handle)

    def move_resize(self, query: str, x: int, y: int, width: int, height: int) -> bool:
        if width < 100 or height < 100:
            raise ValueError("Dimensioni finestra non valide")
        return self.backend.move(self._one(query).handle, int(x), int(y), int(width), int(height))

    def snap(self, query: str, position: str, monitor_index: int = 0) -> bool:
        areas = self.backend.work_areas()
        if not 0 <= monitor_index < len(areas):
            raise ValueError("Monitor non valido")
        left, top, right, bottom = areas[monitor_index]
        width, height = right - left, bottom - top
        layouts = {
            "left": (left, top, width // 2, height),
            "right": (left + width // 2, top, width - width // 2, height),
            "top": (left, top, width, height // 2),
            "bottom": (left, top + height // 2, width, height - height // 2),
            "full": (left, top, width, height),
        }
        if position not in layouts:
            raise ValueError("Posizione snap non valida")
        return self.backend.move(self._one(query).handle, *layouts[position])
