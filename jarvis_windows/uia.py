from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable

from desktop_intelligence import inspect_ui, ui_focus, ui_invoke, ui_set_value
from jarvis_core.errors import ToolError
from jarvis_core.logging import redact


class WindowsUIAgent:
    def __init__(self, observer: Callable[..., dict] = inspect_ui):
        self.observer = observer
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-uia")

    def find_window(self, title: str, *, window_handle: int | None = None) -> dict | None:
        snapshot = self._snapshot(window_handle)
        return snapshot if str(title).casefold() in str(snapshot.get("window", "")).casefold() else None

    def find_element(
        self, target: str, *, control_type: str | None = None, window_handle: int | None = None
    ) -> dict | None:
        needle = str(target).casefold()
        for element in self._snapshot(window_handle).get("elements", []):
            matched = (
                needle in str(element.get("name", "")).casefold()
                or needle == str(element.get("automation_id", "")).casefold()
            )
            typed = not control_type or str(element.get("type", "")).casefold() == control_type.casefold()
            if matched and typed:
                return dict(element)
        return None

    def click_element(
        self, target: str, timeout: float = 5, retries: int = 1, window_handle: int | None = None
    ) -> dict:
        arguments = (target,) if window_handle is None else (target, window_handle)
        return self._act(ui_invoke, *arguments, timeout=timeout, retries=retries)

    def invoke(self, target: str, timeout: float = 5, retries: int = 1, window_handle: int | None = None) -> dict:
        arguments = (target,) if window_handle is None else (target, window_handle)
        return self._act(ui_invoke, *arguments, timeout=timeout, retries=retries)

    def focus(self, target: str, timeout: float = 5, retries: int = 1, window_handle: int | None = None) -> dict:
        arguments = (target,) if window_handle is None else (target, window_handle)
        return self._act(ui_focus, *arguments, timeout=timeout, retries=retries)

    def set_text(
        self, target: str, value: str, timeout: float = 5, retries: int = 1, window_handle: int | None = None
    ) -> dict:
        arguments = (target, value) if window_handle is None else (target, value, window_handle)
        return self._act(ui_set_value, *arguments, timeout=timeout, retries=retries)

    def select_item(self, target: str, timeout: float = 5, retries: int = 1, window_handle: int | None = None) -> dict:
        arguments = (target,) if window_handle is None else (target, window_handle)
        return self._act(ui_invoke, *arguments, timeout=timeout, retries=retries)

    def _act(self, handler, *arguments, timeout: float, retries: int) -> dict:
        last = {"success": False, "message": "UI Automation fallita"}
        for _ in range(max(0, min(int(retries), 5)) + 1):
            future = self._pool.submit(handler, *arguments)
            try:
                last = dict(future.result(timeout=max(0.05, min(float(timeout), 60))) or {})
            except FutureTimeout:
                future.cancel()
                last = {"success": False, "message": "Timeout UI Automation", "error": "timeout"}
            except Exception as exc:
                last = {"success": False, "message": redact(f"{type(exc).__name__}: {exc}")}
            if last.get("success", last.get("successo", False)):
                return last
        return last

    def read_text(self, target: str, *, window_handle: int | None = None) -> str | None:
        element = self.find_element(target, window_handle=window_handle)
        return None if element is None else str(element.get("value") or element.get("name") or "")

    def wait_for_element(self, target: str, *, timeout: float = 5.0, interval: float = 0.05) -> dict | None:
        return self._wait(lambda: self.find_element(target), timeout, interval)

    def wait_until_hidden(self, target: str, *, timeout: float = 5.0, interval: float = 0.05) -> bool:
        return bool(self._wait(lambda: True if self.find_element(target) is None else None, timeout, interval))

    def _snapshot(self, window_handle: int | None = None) -> dict:
        result = self.observer() if window_handle is None else self.observer(window_handle)
        if not result.get("successo", result.get("success", False)):
            raise ToolError(str(result.get("messaggio", "UI Automation non disponibile")))
        return dict(result.get("dati") or result.get("data") or {})

    @staticmethod
    def _wait(probe: Callable[[], object], timeout: float, interval: float):
        deadline = time.monotonic() + max(0.01, float(timeout))
        while time.monotonic() < deadline:
            value = probe()
            if value:
                return value
            threading.Event().wait(max(0.01, min(float(interval), 0.5)))
        return None

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
