from __future__ import annotations

from jarvis_skills import Capability, SkillManifest, SkillRegistry

from .client import ExpansionClient


def _ok_result(value):
    if isinstance(value, dict):
        return value
    return {"success": True, "data": value}


def register_expansion_skills(registry: SkillRegistry, client: ExpansionClient, readiness=None) -> None:
    def reg(
        name,
        description,
        intents,
        permissions,
        entrypoint,
        handler,
        *,
        risk="safe",
        timeout=180.0,
        verification_strategy="handler_result",
    ):
        registry.register(
            SkillManifest(
                name,
                "1.0.0",
                description,
                tuple(intents),
                frozenset(permissions),
                entrypoint,
                risk=risk,
                timeout=float(timeout),
                verification_strategy=verification_strategy,
            ),
            handler,
        )

    reg(
        "expansion.status",
        "Report availability of all optional JARVIS expansion backends",
        ("stato espansioni", "controlla integrazioni avanzate"),
        (),
        "jarvis_expansion:status",
        lambda deep=False: client.status(deep=bool(deep)),
        timeout=30,
    )

    # MCP
    reg("mcp.tools", "List tools exposed by a configured MCP server", ("mcp tools", "strumenti mcp"),
        (Capability.NETWORK,), "jarvis_expansion:mcp_tools",
        lambda server: client.execute("mcp_list_tools", server=server, _timeout=60))
    reg("mcp.call", "Call a tool on a configured MCP server", ("chiama tool mcp", "usa mcp"),
        (Capability.NETWORK,), "jarvis_expansion:mcp_call",
        lambda server, tool, arguments=None: client.execute("mcp_call", server=server, tool=tool, arguments=dict(arguments or {}), _timeout=300),
        risk="sensitive", timeout=300)

    # Keyring: write/delete only. Never expose a skill that reads a secret back into the LLM.
    reg(
        "secrets.store",
        "Store a secret in the Windows credential store",
        (
            "salva segreto",
            "salva password",
            "salva token",
            "salva api key",
            "salva api key in keyring",
            "salva nel keyring",
            "salva nel credential manager",
            "salva nel gestore credenziali",
            "segreto nel keyring",
            "password nel keyring",
            "token nel keyring",
            "api key nel keyring",
            "segreto nel credential manager",
            "password nel credential manager",
            "token nel credential manager",
            "api key nel credential manager",
        ),
        (Capability.SYSTEM_SETTINGS,), "jarvis_expansion:keyring_store",
        lambda service, username, secret: client.execute("keyring_set", service=service, username=username, secret=secret),
        risk="sensitive",
    )
    reg("secrets.delete", "Delete a secret from the Windows credential store", (
        "elimina segreto keyring", "elimina dal keyring", "cancella dal keyring", "rimuovi dal keyring",
        "elimina credenziale", "cancella credenziale", "rimuovi credenziale", "elimina password credential manager",
        "rimuovi token gestore credenziali", "cancella api key keyring",
    ),
        (Capability.SYSTEM_SETTINGS,), "jarvis_expansion:keyring_delete",
        lambda service, username: client.execute("keyring_delete", service=service, username=username), risk="sensitive")

    # Context / web / documents / screen
    reg("screenpipe.search", "Search locally recorded screen/audio context through Screenpipe", ("cerca nella memoria schermo", "screenpipe"),
        (Capability.READ_SCREEN,), "jarvis_expansion:screenpipe_search",
        lambda query="", content_type="all", limit=10: client.execute("screenpipe_search", query=query, content_type=content_type, limit=int(limit)))
    reg("documents.docling", "Parse a document with Docling and return Markdown", ("analizza documento", "docling", "leggi pdf avanzato"),
        (Capability.READ_FILES,), "jarvis_expansion:docling",
        lambda path, max_chars=50000: client.execute("docling_convert", path=path, max_chars=int(max_chars), _timeout=900), timeout=900)
    reg("documents.markitdown", "Convert a file to Markdown using MarkItDown", ("converti file in markdown", "markitdown"),
        (Capability.READ_FILES,), "jarvis_expansion:markitdown",
        lambda path, max_chars=50000: client.execute("markitdown_convert", path=path, max_chars=int(max_chars), _timeout=300), timeout=300)
    reg("web.crawl4ai", "Crawl a web page and extract clean Markdown", ("studia sito", "crawl4ai", "estrai sito"),
        (Capability.NETWORK,), "jarvis_expansion:crawl4ai",
        lambda url, max_chars=60000: client.execute("crawl_url", url=url, max_chars=int(max_chars), _timeout=300), timeout=300)
    reg("screen.dxcam.capture", "Capture the Windows screen using DXcam", ("cattura schermo veloce", "dxcam"),
        (Capability.READ_SCREEN,), "jarvis_expansion:dxcam",
        lambda output="": client.execute("dxcam_capture", output=output, _timeout=30), timeout=30)

    # Home automation
    reg("homeassistant.state", "Read Home Assistant entity state", ("stato home assistant", "stato dispositivo casa"),
        (Capability.NETWORK,), "jarvis_expansion:ha_state",
        lambda entity_id: client.execute("home_assistant_state", entity_id=entity_id))
    reg("homeassistant.service", "Call a Home Assistant service", ("home assistant servizio", "controlla casa"),
        (Capability.NETWORK,), "jarvis_expansion:ha_service",
        lambda domain, service, service_data=None: client.execute("home_assistant_service", domain=domain, service=service, service_data=dict(service_data or {})),
        risk="sensitive")
    reg("esphome.info", "Read ESPHome device information and entities", ("esphome info", "sensore esphome"),
        (Capability.NETWORK,), "jarvis_expansion:esphome_info",
        lambda device: client.execute("esphome_info", device=device, _timeout=60), timeout=60)

    # Model gateways / local AI
    reg("litellm.complete", "Send a prompt through LiteLLM without replacing JARVIS' existing router", ("usa litellm",),
        (Capability.NETWORK,), "jarvis_expansion:litellm",
        lambda model, prompt, max_tokens=512: client.execute("litellm_complete", model=model, prompt=prompt, max_tokens=int(max_tokens), _timeout=180))
    reg("ollama.chat", "Run a chat request against local Ollama", ("usa ollama", "modello locale ollama"),
        (Capability.NETWORK,), "jarvis_expansion:ollama",
        lambda model, prompt: client.execute("ollama_chat", model=model, prompt=prompt, _timeout=300), timeout=300)
    reg("llamacpp.chat", "Run a chat request against a local llama.cpp server", ("usa llama cpp", "llama.cpp"),
        (Capability.NETWORK,), "jarvis_expansion:llamacpp",
        lambda prompt, model="local": client.execute("llamacpp_chat", prompt=prompt, model=model, _timeout=300), timeout=300)

    # Proactivity / memory / coding / search / voice
    reg("watchdog.recent", "Read recent filesystem events observed by Watchdog", ("file cambiati di recente", "eventi watchdog"),
        (Capability.READ_FILES,), "jarvis_expansion:watchdog_recent",
        lambda limit=50: client.execute("watchdog_recent", limit=int(limit)))
    reg(
        "qdrant.add",
        "Add text to JARVIS' local Qdrant semantic store",
        (
            "aggiungi memoria vettoriale",
            "salva in qdrant",
            "salva questo in qdrant",
            "memorizza con qdrant",
            "aggiungi alla memoria vettoriale qdrant",
            "usa qdrant per memorizzare",
            "qdrant add",
        ),
        (Capability.WRITE_FILES,), "jarvis_expansion:qdrant_add",
        # It is an explicit local memory write: the WRITE_FILES capability is
        # still enforced, while completion is gated by the Qdrant read-back.
        lambda text, metadata=None: client.execute("qdrant_add", text=text, metadata=dict(metadata or {}), _timeout=120),
        timeout=120,
        verification_strategy="qdrant_readback",
    )
    reg(
        "qdrant.search",
        "Search JARVIS' local Qdrant semantic store",
        (
            "cerca memoria vettoriale",
            "cerca nella memoria vettoriale",
            "cerca con qdrant",
            "recupera da qdrant",
            "qdrant search",
        ),
        (Capability.READ_FILES,), "jarvis_expansion:qdrant_search",
        lambda query, limit=8: client.execute("qdrant_search", query=query, limit=int(limit), _timeout=120),
        timeout=120,
        verification_strategy="qdrant_query_response",
    )
    def run_openhands(task, workspace=""):
        if readiness is not None and not readiness("openhands", 65.0):
            return {"success": False, "message": "OpenHands non disponibile o non pronto", "data": {}}
        return client.execute("openhands_run", task=task, workspace=workspace, _timeout=1800)

    reg("openhands.run", "Delegate a coding task to OpenHands CLI in headless mode", ("usa openhands", "coding agent openhands"),
        (Capability.READ_FILES, Capability.WRITE_FILES, Capability.PROCESS_CONTROL), "jarvis_expansion:openhands",
        run_openhands, risk="sensitive", timeout=1800)
    reg("searxng.search", "Search the web through a configured SearXNG instance", ("cerca con searxng", "ricerca privata"),
        (Capability.NETWORK,), "jarvis_expansion:searxng",
        lambda query, limit=10: client.execute("searxng_search", query=query, limit=int(limit), _timeout=60), timeout=60)
    reg("ruff.check", "Run Ruff checks on a Python project", ("controlla codice con ruff", "ruff check"),
        (Capability.READ_FILES, Capability.PROCESS_CONTROL), "jarvis_expansion:ruff",
        # Read-only linting is safe; the runtime risk resolver upgrades only
        # fix=True because that mode may modify files.
        lambda path=".", fix=False: client.execute("ruff_check", path=path, fix=bool(fix), _timeout=300), timeout=300)
    reg("voice.silero_vad", "Analyze a WAV file for speech timestamps with Silero VAD", ("analizza voce vad", "silero vad"),
        (Capability.READ_FILES,), "jarvis_expansion:silero_vad",
        lambda path: client.execute("silero_vad", path=path, _timeout=120), timeout=120)
