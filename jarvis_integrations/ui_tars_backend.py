from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .models import IntegrationResult


class UITarsBackend:
    name = "ui_tars"

    def __init__(self, bridge_path: Path, package_dir: Path, *, timeout_seconds: float = 180.0):
        self.bridge_path = Path(bridge_path)
        self.package_dir = Path(package_dir)
        self.timeout_seconds = float(timeout_seconds)

    def _node(self) -> str | None:
        return shutil.which(os.getenv("JARVIS_UI_TARS_NODE", "node"))

    def health(self, *, deep: bool = False) -> IntegrationResult:
        node = self._node()
        if not node:
            return IntegrationResult.fail(self.name, "Node.js non trovato (richiesto Node 20+).")
        if not self.bridge_path.exists():
            return IntegrationResult.fail(self.name, f"Bridge UI-TARS assente: {self.bridge_path}")
        if not (self.package_dir / "node_modules" / "@ui-tars" / "sdk").exists():
            return IntegrationResult.fail(self.name, "Dipendenze UI-TARS non installate. Esegui Installa integrazioni JARVIS.cmd.")
        missing = [name for name in ("UI_TARS_BASE_URL", "UI_TARS_API_KEY", "UI_TARS_MODEL") if not os.getenv(name)]
        if missing:
            return IntegrationResult.fail(self.name, "Configurazione UI-TARS incompleta: " + ", ".join(missing))
        return IntegrationResult.ok(self.name, "UI-TARS configurato", {"node": node, "bridge": str(self.bridge_path)})

    def run(self, task: str) -> IntegrationResult:
        health = self.health()
        if not health.success:
            return health
        try:
            proc = subprocess.run(
                [self._node(), str(self.bridge_path), str(task)],
                cwd=str(self.package_dir),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            if proc.returncode != 0:
                return IntegrationResult.fail(self.name, stderr or stdout or f"UI-TARS exit code {proc.returncode}")
            payload = {}
            if stdout:
                try:
                    payload = json.loads(stdout.splitlines()[-1])
                except json.JSONDecodeError:
                    payload = {"output": stdout[-4000:]}
            if payload.get("ok") is False:
                return IntegrationResult.fail(self.name, str(payload.get("message") or "UI-TARS ha fallito."), payload)
            return IntegrationResult.ok(self.name, str(payload.get("message") or "Task UI-TARS completato."), payload)
        except subprocess.TimeoutExpired:
            return IntegrationResult.fail(self.name, "Timeout UI-TARS.")
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore UI-TARS: {exc}")
