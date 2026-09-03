from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Iterable

from .browser_use_backend import BrowserUseBackend
from .config import IntegrationConfig
from .langgraph_backend import LangGraphBackend
from .mem0_backend import Mem0Backend
from .models import IntegrationResult
from .pipecat_backend import PipecatBackend
from .safety import guard_external_task
from .ufo_backend import UFOBackend
from .ui_tars_backend import UITarsBackend


_BROWSER_MARKERS = (
    "browser", "chrome", "edge", "firefox", "sito", "pagina web", "web", "internet",
    "youtube", "github", "compila il modulo", "form online", "naviga online",
)
_WINDOWS_MARKERS = (
    "windows", "desktop", "finestra", "programma", "app", "impostazioni", "blocco note",
    "notepad", "excel", "word", "powerpoint", "esplora file", "menu start",
)
_VISUAL_MARKERS = (
    "guarda lo schermo", "visivamente", "trova il pulsante", "interfaccia grafica",
    "non trova il controllo", "non riesce a trovare il controllo",
)


class IntegrationService:
    def __init__(self, project_root: Path | None = None):
        self.config = IntegrationConfig.load(project_root)
        self.browser = BrowserUseBackend(
            model=self.config.browser_model,
            max_steps=self.config.browser_max_steps,
            project_root=self.config.project_root,
        )
        self.ufo = UFOBackend(
            self.config.ufo_base_url,
            self.config.ufo_client_id,
            api_key=self.config.ufo_api_key,
            poll_seconds=self.config.ufo_poll_seconds,
            timeout_seconds=self.config.ufo_timeout_seconds,
        )
        self.mem0 = Mem0Backend(user_id=self.config.mem0_user_id)
        self.ui_tars = UITarsBackend(
            self.config.ui_tars_bridge,
            self.config.ui_tars_package_dir,
            timeout_seconds=self.config.ui_tars_timeout_seconds,
        )
        self.pipecat = PipecatBackend()
        self.langgraph = LangGraphBackend()

    def refresh(self) -> None:
        self.__init__(self.config.project_root)

    def _enabled(self, backend: str) -> bool:
        if not self.config.enabled:
            return False
        return {
            "browser_use": self.config.browser_use_enabled,
            "ufo": self.config.ufo_enabled,
            "ui_tars": self.config.ui_tars_enabled,
            "mem0": self.config.mem0_enabled,
            "pipecat": self.config.pipecat_enabled,
            "langgraph": self.config.langgraph_enabled,
        }.get(backend, False)

    def route_candidates(self, task: str, preferred: str = "auto") -> list[str]:
        preferred = str(preferred or "auto").strip().lower()
        if preferred in {"browser_use", "ufo", "ui_tars"}:
            first = [preferred] if self._enabled(preferred) else []
        else:
            text = " ".join(str(task or "").casefold().split())
            if any(marker in text for marker in _VISUAL_MARKERS):
                first = ["ui_tars", "ufo"]
            elif any(marker in text for marker in _BROWSER_MARKERS) or re.search(r"https?://", text):
                first = ["browser_use", "ufo", "ui_tars"]
            elif any(marker in text for marker in _WINDOWS_MARKERS):
                first = ["ufo", "ui_tars"]
            else:
                first = ["ufo", "browser_use", "ui_tars"]
        return [backend for backend in first if self._enabled(backend)]

    def _execute(self, backend: str, task: str, *, max_steps: int | None = None) -> IntegrationResult:
        if backend == "browser_use":
            return self.browser.run(task, max_steps=max_steps)
        if backend == "ufo":
            return self.ufo.run(task)
        if backend == "ui_tars":
            return self.ui_tars.run(task)
        return IntegrationResult.fail(backend, f"Backend esterno sconosciuto: {backend}")

    def delegate(self, task: str, *, preferred: str = "auto", max_steps: int | None = None) -> IntegrationResult:
        if not self.config.enabled:
            return IntegrationResult.fail("integrations", "Integrazioni esterne disabilitate.")
        allowed, reason = guard_external_task(task)
        if not allowed:
            return IntegrationResult.fail("integrations", reason)
        candidates = self.route_candidates(task, preferred=preferred)
        if not candidates:
            return IntegrationResult.fail("integrations", "Nessun backend esterno abilitato per questo task.")

        def execute(backend: str, text: str) -> IntegrationResult:
            return self._execute(backend, text, max_steps=max_steps)

        if self._enabled("langgraph"):
            return self.langgraph.run(str(task), candidates, execute)
        last = None
        for backend in candidates:
            last = execute(backend, str(task))
            if last.success:
                return last
        return last or IntegrationResult.fail("integrations", "Nessun backend ha prodotto un risultato.")

    def run_browser(self, task: str, *, max_steps: int | None = None) -> IntegrationResult:
        allowed, reason = guard_external_task(task)
        if not allowed:
            return IntegrationResult.fail("browser_use", reason)
        if not self._enabled("browser_use"):
            return IntegrationResult.fail("browser_use", "Browser Use disabilitato.")
        return self.browser.run(task, max_steps=max_steps)

    def run_ufo(self, task: str) -> IntegrationResult:
        allowed, reason = guard_external_task(task)
        if not allowed:
            return IntegrationResult.fail("ufo", reason)
        if not self._enabled("ufo"):
            return IntegrationResult.fail("ufo", "UFO disabilitato.")
        return self.ufo.run(task)

    def run_ui_tars(self, task: str) -> IntegrationResult:
        allowed, reason = guard_external_task(task)
        if not allowed:
            return IntegrationResult.fail("ui_tars", reason)
        if not self._enabled("ui_tars"):
            return IntegrationResult.fail("ui_tars", "UI-TARS disabilitato.")
        return self.ui_tars.run(task)

    def status(self, *, deep: bool = False) -> dict:
        rows = {
            "browser_use": self.browser.health(deep=deep) if self.config.browser_use_enabled else IntegrationResult.fail("browser_use", "Disabilitato"),
            "ufo": self.ufo.health(deep=deep) if self.config.ufo_enabled else IntegrationResult.fail("ufo", "Disabilitato"),
            "langgraph": self.langgraph.health(deep=deep) if self.config.langgraph_enabled else IntegrationResult.fail("langgraph", "Disabilitato"),
            "mem0": self.mem0.health(deep=deep) if self.config.mem0_enabled else IntegrationResult.fail("mem0", "Disabilitato"),
            "pipecat": self.pipecat.health(deep=deep) if self.config.pipecat_enabled else IntegrationResult.fail("pipecat", "Disabilitato"),
            "ui_tars": self.ui_tars.health(deep=deep) if self.config.ui_tars_enabled else IntegrationResult.fail("ui_tars", "Disabilitato"),
        }
        return {name: result.as_dict() for name, result in rows.items()}


_SERVICE: IntegrationService | None = None
_SERVICE_LOCK = threading.RLock()


def get_integration_service(project_root: Path | None = None) -> IntegrationService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = IntegrationService(project_root)
        return _SERVICE


def reset_integration_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None
