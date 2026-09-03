from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from settings_store import get_setting


class ExpansionClient:
    """Stdlib-only client for the isolated JARVIS Expansion sidecar."""

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root).resolve()
        self.base_url = str(get_setting("expansion_base_url", "http://127.0.0.1:5199") or "http://127.0.0.1:5199").rstrip("/")
        self.key_path = self.project_root / "external_integrations" / "expansion" / ".jarvis_expansion_key"
        self.timeout = float(get_setting("expansion_timeout_seconds", 180.0) or 180.0)

    def _key(self) -> str:
        try:
            return self.key_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        key = self._key()
        if key:
            headers["X-JARVIS-Expansion-Key"] = key
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                value = json.loads(raw or "{}")
                return value if isinstance(value, dict) else {"success": True, "data": value}
        except HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                data = json.loads(raw or "{}")
            except Exception:
                data = {}
            return {
                "success": False,
                "message": str(data.get("message") or f"Expansion HTTP {exc.code}"),
                "data": data,
            }
        except (URLError, OSError, ValueError) as exc:
            return {"success": False, "message": f"Expansion sidecar non disponibile: {exc}", "data": {}}

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=3.0)

    def status(self, *, deep: bool = False) -> dict[str, Any]:
        return self.execute("status", deep=bool(deep), _timeout=30.0)

    def execute(self, action: str, _timeout: float | None = None, **arguments: Any) -> dict[str, Any]:
        return self._request(
            "POST",
            "/execute",
            {"action": str(action), "arguments": arguments},
            timeout=_timeout,
        )
