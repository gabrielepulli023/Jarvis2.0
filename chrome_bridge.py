import json
import os
import queue
import re
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app_paths import data_path
from jarvis_identity.crypto import protect, unprotect

HOST, PORT = "127.0.0.1", 8765
_LOCK = threading.RLock()
_SNAPSHOT = {}
_COMMANDS = queue.Queue(maxsize=64)
_RESULTS = {}
_SERVER = None


def _load_token():
    configured = os.getenv("JARVIS_CHROME_BRIDGE_TOKEN", "").strip()
    if configured: return configured
    path = data_path("browser") / "bridge_token.dpapi"
    try:
        if path.exists(): return unprotect(path.read_bytes()).decode("ascii")
        value = secrets.token_urlsafe(32); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp"); temporary.write_bytes(protect(value.encode("ascii"))); os.replace(temporary, path)
        return value
    except OSError:
        return secrets.token_urlsafe(32)


TOKEN = _load_token()


def write_extension_config(root=None):
    target = Path(root or Path(__file__).resolve().parent / "chrome_extension") / "local_config.js"
    target.write_text(f'globalThis.JARVIS_BRIDGE_TOKEN = {json.dumps(TOKEN)};\n', encoding="utf-8")
    return str(target)


def _bridge_connected(max_age=8.0):
    with _LOCK:
        received_at = float(_SNAPSHOT.get("received_at", 0) or 0)
    return received_at > 0 and time.time() - received_at <= max(0.1, float(max_age))


def _discard_pending_commands():
    discarded = 0
    while True:
        try:
            _COMMANDS.get_nowait(); _COMMANDS.task_done(); discarded += 1
        except queue.Empty:
            return discarded


def _redact(value):
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items() if str(key).lower() not in {"password", "token", "secret", "authorization", "cookie"}}
    if isinstance(value, list): return [_redact(item) for item in value[:500]]
    if isinstance(value, str):
        return re.sub(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S+", r"\1=[REDACTED]", value[:50000])
    return value


class _Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        return self.headers.get("X-Jarvis-Bridge") == TOKEN

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._authorized():
            return self._json(403, {"error": "forbidden"})
        try: declared_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError: return self._json(400, {"error": "invalid content length"})
        if declared_length < 0 or declared_length > 2_000_000:
            return self._json(413, {"error": "payload too large"})
        length = declared_length
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "invalid json"})
        if self.path == "/snapshot":
            safe = _redact(dict(body)) if isinstance(body, dict) else {}
            safe["received_at"] = time.time()
            with _LOCK:
                _SNAPSHOT.clear(); _SNAPSHOT.update(safe)
            return self._json(200, {"ok": True})
        if self.path == "/result":
            if not isinstance(body, dict) or not body.get("request_id"):
                return self._json(400, {"error": "request_id required"})
            with _LOCK:
                _RESULTS[str(body["request_id"])] = {**_redact(body), "received_at": time.time()}
                if len(_RESULTS) > 256:
                    for key in sorted(_RESULTS, key=lambda item: _RESULTS[item]["received_at"])[:-256]: _RESULTS.pop(key, None)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        if not self._authorized():
            return self._json(403, {"error": "forbidden"})
        if self.path == "/command":
            try:
                command = _COMMANDS.get_nowait()
            except queue.Empty:
                command = None
            if command and command.get("expires_at", 0) < time.time():
                command = None
            return self._json(200, {"command": command})
        return self._json(404, {"error": "not found"})

    def log_message(self, *_):
        return


def ensure_server():
    global _SERVER
    if _SERVER:
        return True
    try:
        write_extension_config()
        _SERVER = ThreadingHTTPServer((HOST, PORT), _Handler)
        _SERVER.daemon_threads = True
        _SERVER.request_queue_size = 16
        threading.Thread(target=_SERVER.serve_forever, daemon=True, name="jarvis-chrome-bridge").start()
        return True
    except OSError:
        return False


def chrome_snapshot():
    ensure_server()
    with _LOCK:
        data = dict(_SNAPSHOT)
    if not data or time.time() - float(data.get("received_at", 0)) > 8:
        try:
            from jarvis_browser import ChromeDevToolsClient
            tabs = ChromeDevToolsClient().tabs()
            page = next((row for row in tabs if row.get("type") == "page" and str(row.get("url", "")).startswith(("http://", "https://"))), None)
            if page:
                return {
                    "successo": True,
                    "messaggio": f"Pagina Chrome rilevata tramite controllo locale: {page.get('title', '')}.",
                    "dati": {**page, "elements": [], "text": "", "source": "cdp", "received_at": time.time()},
                }
        except Exception:
            pass
        return {"successo": False, "messaggio": "Bridge Chrome non collegato. Avvia Chrome tramite JARVIS."}
    return {"successo": True, "messaggio": f"Pagina Chrome letta: {data.get('title', '')}.", "dati": data}


def chrome_action(action, target="", value=""):
    ensure_server()
    allowed = {"click_text", "click_selector", "set_value", "focus", "navigate", "scroll",
               "open_tab", "close_tab", "activate_tab", "list_tabs", "downloads"}
    if action not in allowed:
        return {"successo": False, "messaggio": "Azione Chrome non consentita."}
    if len(str(target)) > 1000 or len(str(value)) > 4000:
        return {"successo": False, "messaggio": "Comando Chrome troppo lungo."}
    if not _bridge_connected():
        _discard_pending_commands()
        cdp_action = {"navigate": "open_tab", "open_tab": "open_tab", "close_tab": "close_tab", "activate_tab": "activate_tab", "list_tabs": "list_tabs"}.get(action)
        if cdp_action:
            try:
                from jarvis_browser import ChromeDevToolsClient
                result = ChromeDevToolsClient().action(cdp_action, target=target, value=value)
                return {
                    "successo": bool(result.get("success")),
                    "messaggio": str(result.get("message") or "Controllo Chrome tramite CDP."),
                    "dati": result.get("data"),
                }
            except Exception:
                pass
        return {"successo": False, "messaggio": "Bridge Chrome non collegato. Il comando non è stato accodato."}
    command = {"request_id": uuid.uuid4().hex, "action": action, "target": str(target), "value": str(value),
               "created_at": time.time(), "expires_at": time.time() + 15.0}
    try: _COMMANDS.put_nowait(command)
    except queue.Full:
        try: _COMMANDS.get_nowait(); _COMMANDS.task_done()
        except queue.Empty: pass
        _COMMANDS.put_nowait(command)
    return {"successo": True, "messaggio": "Comando inviato alla scheda Chrome; verifica con chrome_snapshot.", "request_id": command["request_id"]}


def chrome_command_status(request_id, max_age=60.0):
    with _LOCK: result = dict(_RESULTS.get(str(request_id), {}))
    if not result: return {"successo": False, "messaggio": "Risultato comando non ancora disponibile."}
    if time.time() - result.get("received_at", 0) > max_age: return {"successo": False, "messaggio": "Risultato comando scaduto."}
    return {"successo": bool(result.get("ok")), "messaggio": result.get("error") or "Comando browser verificato.", "dati": result}
