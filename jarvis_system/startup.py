from __future__ import annotations
import sys
from pathlib import Path


class StartupManager:
    def __init__(self, broker, project_root: Path):
        self.broker = broker
        self.project_root = Path(project_root).resolve()

    def _launch(self):
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).resolve()), []
        return str(Path(sys.executable).resolve()), [str(self.project_root / "main.py")]

    def status(self) -> dict:
        response = self.broker.client.execute("startup.status", {})
        return {"success": response.success, "message": response.message, "data": response.data}

    def enable(self) -> dict:
        if hasattr(self.broker, "ensure_available") and not self.broker.ensure_available():
            return {"success": False, "message": "Broker privilegiato non disponibile o elevazione annullata."}
        executable, arguments = self._launch()
        response = self.broker.client.execute(
            "startup.enable", {"executable": executable, "arguments": arguments}, confirmed=True
        )
        return {"success": response.success, "message": response.message, "data": response.data}

    def disable(self) -> dict:
        if hasattr(self.broker, "ensure_available") and not self.broker.ensure_available():
            return {"success": False, "message": "Broker privilegiato non disponibile o elevazione annullata."}
        response = self.broker.client.execute("startup.disable", {}, confirmed=True)
        return {"success": response.success, "message": response.message, "data": response.data}
