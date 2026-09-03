from __future__ import annotations

import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import IntegrationResult


class UFOBackend:
    name = "ufo"

    def __init__(self, base_url: str, client_id: str, *, api_key: str = "", poll_seconds: float = 2.0, timeout_seconds: float = 180.0):
        self.base_url = str(base_url).rstrip("/")
        self.client_id = str(client_id)
        self.api_key = str(api_key or "").strip()
        self.poll_seconds = float(poll_seconds)
        self.timeout_seconds = float(timeout_seconds)

    @staticmethod
    def available() -> bool:
        return True  # HTTP adapter uses only the Python standard library.

    def _json_request(self, method: str, path: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw or "{}")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(f"UFO HTTP {exc.code}: {detail[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"UFO non raggiungibile: {exc.reason}") from exc

    def health(self, *, deep: bool = False) -> IntegrationResult:
        if not deep:
            return IntegrationResult.ok(self.name, "Adapter UFO configurato", {"base_url": self.base_url, "client_id": self.client_id})
        try:
            data = self._json_request("GET", "/api/health", timeout=3.0)
            return IntegrationResult.ok(self.name, "Server UFO raggiungibile", data)
        except Exception as exc:
            return IntegrationResult.fail(self.name, str(exc))

    def run(self, task: str) -> IntegrationResult:
        task_name = f"jarvis_{uuid.uuid4().hex[:12]}"
        try:
            dispatched = self._json_request(
                "POST",
                "/api/dispatch",
                {"client_id": self.client_id, "request": str(task), "task_name": task_name},
                timeout=10.0,
            )
            status = str(dispatched.get("status") or "").lower()
            if status not in {"dispatched", "success", "queued", "pending"}:
                return IntegrationResult.fail(self.name, f"UFO ha rifiutato il task: {status or 'stato sconosciuto'}", dispatched)

            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                result = self._json_request("GET", f"/api/task_result/{task_name}", timeout=10.0)
                result_status = str(result.get("status") or "").lower()
                if result_status in {"done", "completed", "success"}:
                    payload = result.get("result", result)
                    message = "Task UFO completato."
                    if isinstance(payload, dict):
                        message = str(payload.get("observation") or payload.get("action_taken") or message)
                    return IntegrationResult.ok(self.name, message, payload, task_name=task_name)
                if result_status in {"failed", "error", "cancelled", "canceled"}:
                    return IntegrationResult.fail(self.name, f"Task UFO fallito: {result_status}", result, task_name=task_name)
                time.sleep(self.poll_seconds)
            return IntegrationResult.fail(self.name, "Timeout in attesa del risultato UFO.", task_name=task_name)
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore UFO: {exc}", task_name=task_name)
