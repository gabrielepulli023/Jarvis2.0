from __future__ import annotations
import json
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class ChromeDevToolsClient:
    """Loopback-only, bounded CDP discovery fallback without arbitrary JavaScript."""

    _ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

    def __init__(self, port: int = 9222):
        if not 1 <= int(port) <= 65535:
            raise ValueError("Porta CDP non valida")
        self.base = f"http://127.0.0.1:{int(port)}"

    def _request(self, path: str, method: str = "GET"):
        request = Request(self.base + path, method=method, headers={"Accept": "application/json"})
        with urlopen(request, timeout=2) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError("Risposta CDP troppo grande")
        # Chrome restituisce spesso un body vuoto per /json/close e
        # /json/activate: il codice HTTP è l'evidenza dell'operazione.
        return json.loads(payload) if payload.strip() else {}

    def tabs(self) -> list[dict]:
        rows = self._request("/json/list")
        if not isinstance(rows, list):
            raise ValueError("Risposta CDP non valida")
        return [
            {
                "id": str(row.get("id", "")),
                "title": str(row.get("title", ""))[:1000],
                "url": str(row.get("url", ""))[:4000],
                "type": str(row.get("type", "")),
            }
            for row in rows[:500]
            if isinstance(row, dict)
        ]

    def action(self, action: str, target: str = "", value: str = "", **_) -> dict:
        if action == "list_tabs":
            return {
                "success": True,
                "message": "Schede lette tramite CDP.",
                "data": {"tabs": self.tabs(), "fallback": "cdp"},
            }
        if action == "open_tab":
            url = str(target or value)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return {"success": False, "message": "URL CDP non valido."}
            row = self._request("/json/new?" + quote(url, safe=""), "PUT")
            return {
                "success": bool(row),
                "message": "Scheda aperta tramite CDP.",
                "data": {"tab": row, "fallback": "cdp"},
            }
        if action in {"close_tab", "activate_tab"}:
            identity = str(target)
            if not self._ID.fullmatch(identity):
                return {"success": False, "message": "ID scheda CDP non valido."}
            command = "close" if action == "close_tab" else "activate"
            try:
                row = self._request(f"/json/{command}/{identity}")
            except json.JSONDecodeError:
                # Il server CDP può rispondere con testo semplice dopo aver
                # accettato l'operazione; la chiamata HTTP è l'evidenza.
                row = {}
            return {
                "success": True,
                "message": f"Scheda {command} tramite CDP.",
                "data": {"result": row, "fallback": "cdp"},
            }
        return {"success": False, "message": "Azione non disponibile nel fallback CDP senza JavaScript arbitrario."}
