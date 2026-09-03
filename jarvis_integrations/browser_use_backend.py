from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .models import IntegrationResult

_RESULT_PREFIX = "JARVIS_BROWSER_RESULT="


class BrowserUseBackend:
    """Browser Use sidecar.

    Browser Use is intentionally executed in its own virtual environment because
    browser-use 0.13.8 pins openai==2.16.0 while the stable JARVIS runtime pins a
    newer OpenAI SDK. Keeping it out-of-process prevents dependency downgrades in
    the main assistant.
    """

    name = "browser_use"

    def __init__(
        self,
        *,
        model: str = "",
        max_steps: int = 25,
        project_root: Path | str | None = None,
    ):
        self.model = str(model or "").strip()
        self.max_steps = int(max_steps)
        self.project_root = Path(
            project_root or Path(__file__).resolve().parent.parent
        ).resolve()

    @property
    def sidecar_dir(self) -> Path:
        return self.project_root / "external_integrations" / "browser_use"

    @property
    def python_exe(self) -> Path:
        return self.sidecar_dir / ".browser-use-env" / "Scripts" / "python.exe"

    @property
    def runner(self) -> Path:
        return self.sidecar_dir / "browser_use_runner.py"

    def available(self) -> bool:
        if not self.python_exe.exists() or not self.runner.exists():
            return False
        try:
            proc = subprocess.run(
                [str(self.python_exe), "-c", "import browser_use"],
                capture_output=True,
                text=True,
                timeout=12,
                env=self._env(),
            )
            return proc.returncode == 0
        except Exception:
            return False

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def health(self, *, deep: bool = False) -> IntegrationResult:
        if not self.python_exe.exists():
            return IntegrationResult.fail(
                self.name,
                "Ambiente Browser Use isolato non installato. Esegui 'Installa integrazioni JARVIS.cmd'.",
            )
        if not self.runner.exists():
            return IntegrationResult.fail(self.name, "Runner Browser Use sidecar mancante.")
        if deep and not self.available():
            return IntegrationResult.fail(self.name, "browser-use non importabile nel sidecar isolato.")
        configured = bool(
            os.getenv("BROWSER_USE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        if not configured:
            return IntegrationResult.fail(
                self.name,
                "Browser Use installato, ma manca una chiave LLM compatibile.",
            )
        return IntegrationResult.ok(self.name, "Browser Use sidecar disponibile")

    def run(self, task: str, *, max_steps: int | None = None) -> IntegrationResult:
        task = str(task or "").strip()
        if not task:
            return IntegrationResult.fail(self.name, "Task Browser Use vuoto.")

        if not self.python_exe.exists() or not self.runner.exists():
            return IntegrationResult.fail(
                self.name,
                "Browser Use sidecar non installato. Esegui 'Installa integrazioni JARVIS.cmd'.",
            )

        payload: dict[str, Any] = {
            "task": task,
            "model": self.model,
            "max_steps": max(1, min(100, int(max_steps or self.max_steps))),
        }
        try:
            proc = subprocess.run(
                [str(self.python_exe), str(self.runner)],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                env=self._env(),
                cwd=str(self.sidecar_dir),
            )
        except subprocess.TimeoutExpired:
            return IntegrationResult.fail(self.name, "Timeout Browser Use sidecar.")
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore avvio Browser Use sidecar: {exc}")

        result_payload = None
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith(_RESULT_PREFIX):
                try:
                    result_payload = json.loads(line[len(_RESULT_PREFIX):])
                except Exception:
                    result_payload = None
                break

        if isinstance(result_payload, dict):
            if result_payload.get("success"):
                return IntegrationResult.ok(
                    self.name,
                    str(result_payload.get("message") or "Browser Use completato."),
                    result_payload.get("data"),
                )
            return IntegrationResult.fail(
                self.name,
                str(result_payload.get("message") or "Browser Use sidecar fallito."),
                result_payload,
            )

        detail = (proc.stderr or proc.stdout or "").strip()
        if len(detail) > 1500:
            detail = detail[-1500:]
        return IntegrationResult.fail(
            self.name,
            f"Browser Use sidecar terminato senza risultato valido (exit {proc.returncode}). {detail}",
        )
