from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import shlex
import subprocess
import sys
import time
import traceback
import uuid
from collections import deque
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_CONFIG = {
    "screenpipe_url": "http://127.0.0.1:3030",
    "home_assistant_url": "http://homeassistant.local:8123",
    "ollama_url": "http://127.0.0.1:11434",
    "llamacpp_url": "http://127.0.0.1:8080",
    "searxng_url": "http://127.0.0.1:8088",
    "watchdog_enabled": True,
    "watchdog_paths": ["~/Desktop", "~/Documents", "~/Downloads"],
    "qdrant_model": "sentence-transformers/all-MiniLM-L6-v2",
    "mcp_servers": {},
    "esphome_devices": {},
    "opentelemetry_service_name": "jarvis-expansion",
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except Exception:
            return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _jsonable(vars(value))
        except Exception:
            pass
    return str(value)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _http_json(method: str, url: str, *, payload: Any = None, headers: dict[str, str] | None = None, timeout: float = 10.0) -> Any:
    body = None
    hdrs = dict(headers or {})
    hdrs.setdefault("Accept", "application/json")
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    req = Request(url, data=body, headers=hdrs, method=method)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


class ExpansionEngine:
    def __init__(self, config_path: Path, data_dir: Path):
        self.config_path = Path(config_path)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
        self.events: deque[dict[str, Any]] = deque(maxlen=1000)
        self._observer = None
        self._qdrant = None
        self._docling = None
        self._markitdown = None
        self._tracer = self._setup_otel()
        self._start_watchdog()

    def _load_config(self) -> dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
        return cfg

    def _setup_otel(self):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": str(self.config.get("opentelemetry_service_name") or "jarvis-expansion")}))
            endpoint = str(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
            if endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
            trace.set_tracer_provider(provider)
            return trace.get_tracer("jarvis.expansion")
        except Exception:
            return None

    def span(self, action: str):
        if self._tracer is None:
            return nullcontext()
        return self._tracer.start_as_current_span(f"expansion.{action}")

    def _start_watchdog(self) -> None:
        if not bool(self.config.get("watchdog_enabled", True)):
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            engine = self

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    engine.events.append({
                        "time": time.time(),
                        "event": str(getattr(event, "event_type", "unknown")),
                        "path": str(getattr(event, "src_path", "")),
                        "destination": str(getattr(event, "dest_path", "")),
                        "directory": bool(getattr(event, "is_directory", False)),
                    })

            observer = Observer()
            scheduled = 0
            for raw in self.config.get("watchdog_paths", []):
                path = Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()
                if path.exists() and path.is_dir():
                    observer.schedule(Handler(), str(path), recursive=True)
                    scheduled += 1
            if scheduled:
                observer.daemon = True
                observer.start()
                self._observer = observer
        except Exception:
            self._observer = None

    def shutdown(self) -> None:
        observer = self._observer
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=3)
            except Exception:
                pass
        qdrant = self._qdrant
        self._qdrant = None
        if qdrant is not None:
            qdrant.close()

    def _secret(self, service: str, username: str) -> str:
        try:
            import keyring
            return str(keyring.get_password(service, username) or "")
        except Exception:
            return ""

    def status(self, deep: bool = False) -> dict[str, Any]:
        checks: dict[str, Any] = {
            "mcp": {"installed": _module_available("mcp")},
            "fastmcp": {"installed": _module_available("fastmcp")},
            "keyring": {"installed": _module_available("keyring")},
            "screenpipe": {"configured": True},
            "docling": {"installed": _module_available("docling")},
            "crawl4ai": {"installed": _module_available("crawl4ai")},
            "opentelemetry": {"installed": _module_available("opentelemetry.sdk"), "tracing": self._tracer is not None},
            "dxcam": {"installed": _module_available("dxcam"), "windows": sys.platform == "win32"},
            "home_assistant": {"url": self.config.get("home_assistant_url"), "token_configured": bool(self._secret("jarvis.home_assistant", "token"))},
            "esphome": {"installed": _module_available("aioesphomeapi"), "devices": sorted((self.config.get("esphome_devices") or {}).keys())},
            "litellm": {"installed": _module_available("litellm")},
            "ollama": {"url": self.config.get("ollama_url")},
            "llama_cpp": {"url": self.config.get("llamacpp_url")},
            "watchdog": {"installed": _module_available("watchdog"), "running": self._observer is not None, "events": len(self.events)},
            "qdrant": {"installed": _module_available("qdrant_client")},
            "openhands": {"cli": shutil.which("openhands") or "", "wsl": bool(shutil.which("wsl.exe")) if sys.platform == "win32" else False},
            "searxng": {"url": self.config.get("searxng_url")},
            "ruff": {"installed": _module_available("ruff") or bool(shutil.which("ruff"))},
            "markitdown": {"installed": _module_available("markitdown")},
            "silero_vad": {"installed": _module_available("silero_vad")},
        }
        if deep:
            checks["screenpipe"]["online"] = self._probe_url(str(self.config.get("screenpipe_url")), "/search?limit=1&content_type=all")
            checks["home_assistant"]["online"] = self._ha_probe()
            checks["ollama"]["online"] = self._probe_url(str(self.config.get("ollama_url")), "/api/tags")
            checks["llama_cpp"]["online"] = self._probe_url(str(self.config.get("llamacpp_url")), "/v1/models")
            checks["searxng"]["online"] = self._probe_url(str(self.config.get("searxng_url")), "/search?q=jarvis&format=json")
        return checks

    def _probe_url(self, base: str, path: str) -> bool:
        if not base:
            return False
        headers = {}
        # Screenpipe returns 401 when auth is enabled.  Use the same Keyring
        # secret as screenpipe_search, without ever exposing it in diagnostics.
        if path.startswith("/search") and str(self.config.get("screenpipe_url") or "").rstrip("/") == base.rstrip("/"):
            token = self._secret("jarvis.screenpipe", "api_key")
            if token:
                headers = {"Authorization": f"Bearer {token}", "X-API-Key": token}
        try:
            _http_json("GET", base.rstrip("/") + path, headers=headers, timeout=2.5)
            return True
        except Exception:
            return False

    def _ha_headers(self) -> dict[str, str]:
        token = self._secret("jarvis.home_assistant", "token")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _ha_probe(self) -> bool:
        base = str(self.config.get("home_assistant_url") or "").rstrip("/")
        if not base or not self._ha_headers():
            return False
        try:
            _http_json("GET", base + "/api/", headers=self._ha_headers(), timeout=3)
            return True
        except Exception:
            return False

    async def _mcp_session(self, name: str, callback):
        from mcp import ClientSession, StdioServerParameters
        cfg = (self.config.get("mcp_servers") or {}).get(str(name))
        if not isinstance(cfg, dict):
            raise ValueError(f"Server MCP non configurato: {name}")
        kind = str(cfg.get("transport") or ("http" if cfg.get("url") else "stdio")).lower()
        if kind in {"http", "streamable_http", "streamable-http"}:
            from mcp.client.streamable_http import streamablehttp_client
            url = str(cfg.get("url") or "").strip()
            if not url:
                raise ValueError("URL MCP mancante")
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)
        if kind == "stdio":
            from mcp.client.stdio import stdio_client
            command = str(cfg.get("command") or "").strip()
            if not command:
                raise ValueError("Comando MCP mancante")
            args = [str(x) for x in cfg.get("args", [])]
            env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
            params = StdioServerParameters(command=command, args=args, env=env or None)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)
        raise ValueError(f"Transport MCP non supportato: {kind}")

    def mcp_list_tools(self, server: str) -> dict[str, Any]:
        async def work(session):
            value = await session.list_tools()
            return [_jsonable(tool) for tool in value.tools]
        return {"tools": asyncio.run(self._mcp_session(server, work))}

    def mcp_call(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async def work(session):
            value = await session.call_tool(str(tool), arguments=dict(arguments or {}))
            return _jsonable(value)
        return {"result": asyncio.run(self._mcp_session(server, work))}

    def keyring_set(self, service: str, username: str, secret: str) -> dict[str, Any]:
        import keyring
        keyring.set_password(str(service), str(username), str(secret))
        return {"stored": True, "service": str(service), "username": str(username)}

    def keyring_delete(self, service: str, username: str) -> dict[str, Any]:
        import keyring
        try:
            keyring.delete_password(str(service), str(username))
            deleted = True
        except Exception:
            deleted = False
        return {"deleted": deleted, "service": str(service), "username": str(username)}

    def screenpipe_search(self, query: str = "", content_type: str = "all", limit: int = 10) -> Any:
        base = str(self.config.get("screenpipe_url") or "http://127.0.0.1:3030").rstrip("/")
        params = urlencode({"q": str(query), "content_type": str(content_type), "limit": max(1, min(100, int(limit)))})
        headers = {}
        api_key = self._secret("jarvis.screenpipe", "api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key
        return _http_json("GET", f"{base}/search?{params}", headers=headers, timeout=20)

    def docling_convert(self, path: str, max_chars: int = 50000) -> dict[str, Any]:
        from docling.document_converter import DocumentConverter
        source = Path(path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(source)
        if self._docling is None:
            self._docling = DocumentConverter()
        result = self._docling.convert(str(source))
        text = result.document.export_to_markdown()
        limit = max(1000, min(500000, int(max_chars)))
        return {"path": str(source), "markdown": text[:limit], "truncated": len(text) > limit}

    def markitdown_convert(self, path: str, max_chars: int = 50000) -> dict[str, Any]:
        from markitdown import MarkItDown
        source = Path(path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(source)
        if self._markitdown is None:
            self._markitdown = MarkItDown(enable_plugins=False)
        result = self._markitdown.convert(str(source))
        text = str(result.text_content or "")
        limit = max(1000, min(500000, int(max_chars)))
        return {"path": str(source), "markdown": text[:limit], "truncated": len(text) > limit}

    def crawl_url(self, url: str, max_chars: int = 60000) -> dict[str, Any]:
        from crawl4ai import AsyncWebCrawler

        async def work():
            async with AsyncWebCrawler() as crawler:
                return await crawler.arun(str(url))

        result = asyncio.run(work())
        markdown = str(getattr(result, "markdown", "") or "")
        limit = max(1000, min(500000, int(max_chars)))
        return {
            "url": str(url),
            "success": bool(getattr(result, "success", True)),
            "markdown": markdown[:limit],
            "truncated": len(markdown) > limit,
        }

    def dxcam_capture(self, output: str = "") -> dict[str, Any]:
        if sys.platform != "win32":
            raise RuntimeError("DXcam è disponibile solo su Windows")
        import dxcam
        from PIL import Image
        camera = dxcam.create(output_color="RGB")
        frame = camera.grab()
        if frame is None:
            raise RuntimeError("DXcam non ha restituito un frame")
        if output:
            path = Path(output).expanduser().resolve()
        else:
            folder = self.data_dir / "captures"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"dxcam_{int(time.time() * 1000)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame).save(path)
        return {"path": str(path), "width": int(frame.shape[1]), "height": int(frame.shape[0])}

    def home_assistant_state(self, entity_id: str) -> Any:
        base = str(self.config.get("home_assistant_url") or "").rstrip("/")
        if not self._ha_headers():
            raise RuntimeError("Token Home Assistant non configurato in Keyring")
        return _http_json("GET", f"{base}/api/states/{entity_id}", headers=self._ha_headers(), timeout=10)

    def home_assistant_service(self, domain: str, service: str, service_data: dict[str, Any] | None = None) -> Any:
        base = str(self.config.get("home_assistant_url") or "").rstrip("/")
        if not self._ha_headers():
            raise RuntimeError("Token Home Assistant non configurato in Keyring")
        return _http_json(
            "POST", f"{base}/api/services/{domain}/{service}",
            payload=dict(service_data or {}), headers=self._ha_headers(), timeout=20,
        )

    def esphome_info(self, device: str) -> dict[str, Any]:
        import aioesphomeapi
        cfg = (self.config.get("esphome_devices") or {}).get(str(device))
        if not isinstance(cfg, dict):
            raise ValueError(f"Dispositivo ESPHome non configurato: {device}")
        host = str(cfg.get("host") or "").strip()
        port = int(cfg.get("port") or 6053)
        noise_psk = str(cfg.get("noise_psk") or "").strip() or None
        password = self._secret(f"jarvis.esphome.{device}", "password") or None

        async def work():
            api = aioesphomeapi.APIClient(host, port, password=password, noise_psk=noise_psk)
            await api.connect(login=True)
            try:
                info = await api.device_info()
                entities = await api.list_entities_services()
                return {"device_info": _jsonable(info), "entities": _jsonable(entities)}
            finally:
                await api.disconnect()

        return asyncio.run(work())

    def litellm_complete(self, model: str, prompt: str, max_tokens: int = 512) -> dict[str, Any]:
        from litellm import completion
        # Optional secrets can be stored without ever returning them to JARVIS.
        secret_map = {
            "OPENAI_API_KEY": ("jarvis.openai", "api_key"),
            "ANTHROPIC_API_KEY": ("jarvis.anthropic", "api_key"),
            "GEMINI_API_KEY": ("jarvis.gemini", "api_key"),
        }
        for env_name, (service, username) in secret_map.items():
            if not os.getenv(env_name):
                value = self._secret(service, username)
                if value:
                    os.environ[env_name] = value
        response = completion(
            model=str(model),
            messages=[{"role": "user", "content": str(prompt)}],
            max_tokens=max(1, min(8192, int(max_tokens))),
        )
        text = ""
        try:
            text = response.choices[0].message.content
        except Exception:
            text = str(response)
        return {"model": str(model), "text": text}

    def ollama_chat(self, model: str, prompt: str) -> dict[str, Any]:
        base = str(self.config.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
        value = _http_json("POST", base + "/api/chat", payload={
            "model": str(model), "messages": [{"role": "user", "content": str(prompt)}], "stream": False,
        }, timeout=300)
        return _jsonable(value)

    def llamacpp_chat(self, prompt: str, model: str = "local") -> dict[str, Any]:
        base = str(self.config.get("llamacpp_url") or "http://127.0.0.1:8080").rstrip("/")
        value = _http_json("POST", base + "/v1/chat/completions", payload={
            "model": str(model), "messages": [{"role": "user", "content": str(prompt)}], "stream": False,
        }, timeout=300)
        return _jsonable(value)

    def watchdog_recent(self, limit: int = 50) -> dict[str, Any]:
        count = max(1, min(500, int(limit)))
        rows = list(self.events)[-count:]
        return {"events": rows, "watching": self._observer is not None}

    def _qdrant_client(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            path = self.data_dir / "qdrant"
            path.mkdir(parents=True, exist_ok=True)
            self._qdrant = QdrantClient(path=str(path))
        return self._qdrant

    def _qdrant_ensure_collection(self, collection: str, model_name: str) -> None:
        from qdrant_client import models
        client = self._qdrant_client()
        exists = False
        try:
            exists = bool(client.collection_exists(collection))
        except Exception:
            try:
                client.get_collection(collection)
                exists = True
            except Exception:
                exists = False
        if not exists:
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=client.get_embedding_size(model_name), distance=models.Distance.COSINE),
            )

    def qdrant_add(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        from qdrant_client import models
        model_name = str(self.config.get("qdrant_model") or DEFAULT_CONFIG["qdrant_model"])
        collection = "jarvis_expansion_memory"
        self._qdrant_ensure_collection(collection, model_name)
        point_id = str(uuid.uuid4())
        doc = models.Document(text=str(text), model=model_name)
        self._qdrant_client().upload_collection(
            collection_name=collection,
            vectors=[doc],
            ids=[point_id],
            payload=[{"text": str(text), **dict(metadata or {})}],
        )
        stored = self._qdrant_client().retrieve(
            collection_name=collection,
            ids=[point_id],
            with_payload=True,
        )
        if not stored:
            raise RuntimeError("Qdrant non ha restituito il punto appena scritto")
        return {
            "id": point_id,
            "collection": collection,
            "verified": True,
            "verification_evidence": "Punto recuperato da Qdrant dopo upload",
        }

    def qdrant_search(self, query: str, limit: int = 8) -> dict[str, Any]:
        from qdrant_client import models
        model_name = str(self.config.get("qdrant_model") or DEFAULT_CONFIG["qdrant_model"])
        collection = "jarvis_expansion_memory"
        self._qdrant_ensure_collection(collection, model_name)
        result = self._qdrant_client().query_points(
            collection_name=collection,
            query=models.Document(text=str(query), model=model_name),
            limit=max(1, min(50, int(limit))),
            with_payload=True,
        )
        return {
            "points": _jsonable(getattr(result, "points", result)),
            "collection": collection,
            "verified": True,
            "verification_evidence": "Query Qdrant completata e risposta serializzata",
        }

    def openhands_run(self, task: str, workspace: str = "") -> dict[str, Any]:
        cwd = Path(workspace).expanduser().resolve() if str(workspace).strip() else Path.cwd()
        if not cwd.exists() or not cwd.is_dir():
            raise FileNotFoundError(cwd)
        exe = shutil.which("openhands")
        if exe:
            cmd = [exe, "--headless", "--json", "-t", str(task)]
            completed = subprocess.run(
                cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
            )
        elif sys.platform == "win32" and shutil.which("wsl.exe"):
            # OpenHands CLI officially supports Windows through WSL. Translate the
            # workspace path inside WSL and keep the task shell-quoted.
            win_path = str(cwd)
            script = (
                'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; '
                f'cd "$(wslpath -a {shlex.quote(win_path)})" && '
                f'openhands --headless --json -t {shlex.quote(str(task))}'
            )
            completed = subprocess.run(
                ["wsl.exe", "bash", "-lc", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
            )
        else:
            raise RuntimeError("OpenHands CLI non trovato. Su Windows installalo in WSL.")
        stdout = completed.stdout[-100000:]
        stderr = completed.stderr[-20000:]
        parsed = None
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None
        return {"returncode": completed.returncode, "result": parsed if parsed is not None else stdout, "stderr": stderr}

    def searxng_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        base = str(self.config.get("searxng_url") or "http://127.0.0.1:8088").rstrip("/")
        params = urlencode({"q": str(query), "format": "json"})
        value = _http_json("GET", base + "/search?" + params, timeout=30)
        rows = value.get("results", []) if isinstance(value, dict) else []
        return {"query": str(query), "results": _jsonable(rows[: max(1, min(50, int(limit)))])}

    def ruff_check(self, path: str = ".", fix: bool = False) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(target)
        cmd = [sys.executable, "-m", "ruff", "check", str(target), "--output-format", "concise"]
        if bool(fix):
            cmd.append("--fix")
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        return {
            "returncode": completed.returncode,
            "clean": completed.returncode == 0,
            "stdout": completed.stdout[-100000:],
            "stderr": completed.stderr[-20000:],
        }

    def silero_vad(self, path: str) -> dict[str, Any]:
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio
        source = Path(path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(source)
        model = load_silero_vad()
        audio = read_audio(str(source))
        timestamps = get_speech_timestamps(audio, model, return_seconds=True)
        return {"path": str(source), "speech": _jsonable(timestamps)}

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "status": lambda: self.status(bool(arguments.get("deep", False))),
            "mcp_list_tools": lambda: self.mcp_list_tools(arguments.get("server", "")),
            "mcp_call": lambda: self.mcp_call(arguments.get("server", ""), arguments.get("tool", ""), arguments.get("arguments") or {}),
            "keyring_set": lambda: self.keyring_set(arguments.get("service", ""), arguments.get("username", ""), arguments.get("secret", "")),
            "keyring_delete": lambda: self.keyring_delete(arguments.get("service", ""), arguments.get("username", "")),
            "screenpipe_search": lambda: self.screenpipe_search(arguments.get("query", ""), arguments.get("content_type", "all"), arguments.get("limit", 10)),
            "docling_convert": lambda: self.docling_convert(arguments.get("path", ""), arguments.get("max_chars", 50000)),
            "markitdown_convert": lambda: self.markitdown_convert(arguments.get("path", ""), arguments.get("max_chars", 50000)),
            "crawl_url": lambda: self.crawl_url(arguments.get("url", ""), arguments.get("max_chars", 60000)),
            "dxcam_capture": lambda: self.dxcam_capture(arguments.get("output", "")),
            "home_assistant_state": lambda: self.home_assistant_state(arguments.get("entity_id", "")),
            "home_assistant_service": lambda: self.home_assistant_service(arguments.get("domain", ""), arguments.get("service", ""), arguments.get("service_data") or {}),
            "esphome_info": lambda: self.esphome_info(arguments.get("device", "")),
            "litellm_complete": lambda: self.litellm_complete(arguments.get("model", ""), arguments.get("prompt", ""), arguments.get("max_tokens", 512)),
            "ollama_chat": lambda: self.ollama_chat(arguments.get("model", ""), arguments.get("prompt", "")),
            "llamacpp_chat": lambda: self.llamacpp_chat(arguments.get("prompt", ""), arguments.get("model", "local")),
            "watchdog_recent": lambda: self.watchdog_recent(arguments.get("limit", 50)),
            "qdrant_add": lambda: self.qdrant_add(arguments.get("text", ""), arguments.get("metadata") or {}),
            "qdrant_search": lambda: self.qdrant_search(arguments.get("query", ""), arguments.get("limit", 8)),
            "openhands_run": lambda: self.openhands_run(arguments.get("task", ""), arguments.get("workspace", "")),
            "searxng_search": lambda: self.searxng_search(arguments.get("query", ""), arguments.get("limit", 10)),
            "ruff_check": lambda: self.ruff_check(arguments.get("path", "."), bool(arguments.get("fix", False))),
            "silero_vad": lambda: self.silero_vad(arguments.get("path", "")),
        }
        handler = handlers.get(str(action))
        if handler is None:
            raise ValueError(f"Azione Expansion sconosciuta: {action}")
        with self.span(str(action)):
            return _jsonable(handler())


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVISExpansion/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def _authorized(self) -> bool:
        return self.headers.get("X-JARVIS-Expansion-Key", "") == self.server.token

    def _send(self, code: int, payload: dict[str, Any]):
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._authorized():
            self._send(403, {"success": False, "message": "Forbidden"})
            return
        if self.path == "/health":
            self._send(200, {"success": True, "status": "healthy", "version": 1})
            return
        self._send(404, {"success": False, "message": "Not found"})

    def do_POST(self):
        if not self._authorized():
            self._send(403, {"success": False, "message": "Forbidden"})
            return
        if self.path != "/execute":
            self._send(404, {"success": False, "message": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            request = json.loads(body or "{}")
            action = str(request.get("action") or "")
            arguments = request.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("arguments deve essere un oggetto JSON")
            data = self.server.engine.execute(action, arguments)
            self._send(200, {"success": True, "message": "Operazione completata.", "data": data, "backend": action})
        except Exception as exc:
            traceback.print_exc()
            self._send(500, {"success": False, "message": f"{type(exc).__name__}: {exc}", "data": {}})


class ExpansionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, token: str, engine: ExpansionEngine):
        super().__init__(address, handler)
        self.token = token
        self.engine = engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5199)
    parser.add_argument("--token", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Expansion server may bind only to localhost")
    engine = ExpansionEngine(Path(args.config), Path(args.data_dir))
    server = ExpansionHTTPServer((args.host, args.port), Handler, token=args.token, engine=engine)
    print(f"JARVIS Expansion server listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        engine.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
