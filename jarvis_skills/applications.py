from __future__ import annotations
import importlib
import shutil
import threading
from pathlib import Path
from urllib.parse import quote_plus
from .registry import Capability, SkillManifest, SkillRegistry, SkillResult


def register_application_skills(registry: SkillRegistry, processes, memory, workspace: Path) -> None:
    root = Path(workspace).resolve()

    def _legacy_result(value):
        if isinstance(value, tuple) and len(value) >= 2:
            return {"success": bool(value[0]), "message": str(value[1])}
        return value

    def app_open(name: str):
        return _legacy_result(importlib.import_module("tools").apri_programma(name))

    def app_close(name: str):
        return _legacy_result(importlib.import_module("tools").chiudi_programma(name))

    registry.register(
        SkillManifest(
            "applications.open",
            "1.0.0",
            "Open a known installed application",
            ("open app", "apri programma"),
            frozenset({Capability.PROCESS_CONTROL}),
            "applications:open",
            risk="safe",
            verification_strategy="process_or_window",
        ),
        app_open,
    )
    registry.register(
        SkillManifest(
            "applications.close",
            "1.0.0",
            "Gracefully close a known application",
            ("close app", "chiudi programma"),
            frozenset({Capability.PROCESS_CONTROL}),
            "applications:close",
            risk="sensitive",
            verification_strategy="process_or_window_hidden",
        ),
        app_close,
    )

    def vscode_open(project: str):
        path = Path(project).resolve()
        if not path.exists() or not path.is_dir():
            return {"successo": False, "messaggio": "Progetto VS Code non trovato."}
        executable = shutil.which("code") or shutil.which("code.cmd")
        if not executable:
            return {"successo": False, "messaggio": "CLI di Visual Studio Code non trovata nel PATH."}
        item = processes.start([executable, "--reuse-window", str(path)], cwd=root)
        threading.Event().wait(0.15)
        code = item.process.poll()
        return {
            "successo": code in {None, 0},
            "messaggio": "Progetto inviato a Visual Studio Code." if code in {None, 0} else "Avvio VS Code fallito.",
            "dati": {"project": str(path), "pid": item.process.pid, "returncode": code},
        }

    registry.register(
        SkillManifest(
            "vscode.open_project",
            "1.0.0",
            "Open an existing project in VS Code",
            ("open vscode project", "apri progetto vscode"),
            frozenset({Capability.PROCESS_CONTROL, Capability.READ_FILES}),
            "applications:vscode_open",
        ),
        vscode_open,
    )

    def youtube_search(query: str):
        return registry.execute(
            "browser.dom",
            action="navigate",
            target=f"https://www.youtube.com/results?search_query={quote_plus(str(query))}",
            expected={},
            timeout=8,
        )

    def youtube_play(target: str):
        return registry.execute("browser.dom", action="click_text", target=str(target), expected={}, timeout=8)

    registry.register(
        SkillManifest(
            "youtube.search",
            "1.0.0",
            "Search YouTube through verified DOM navigation",
            ("youtube search", "cerca youtube"),
            frozenset({Capability.BROWSER_CONTROL}),
            "applications:youtube_search",
        ),
        youtube_search,
    )
    registry.register(
        SkillManifest(
            "youtube.play",
            "1.0.0",
            "Play a visible YouTube result",
            ("play youtube", "riproduci youtube"),
            frozenset({Capability.BROWSER_CONTROL}),
            "applications:youtube_play",
        ),
        youtube_play,
    )

    def trading_snapshot():
        result = registry.execute("browser.snapshot")
        if not result.success:
            return result
        data = result.data
        text = " ".join(str(data.get(key, "")) for key in ("title", "url", "text"))
        return SkillResult(
            True,
            "Contesto TradingView acquisito.",
            {"title": data.get("title"), "url": data.get("url"), "text": text[:10000]},
            "tradingview.snapshot",
            result.fallback_used,
        )

    def trading_analyze(question: str = "Analizza il grafico TradingView visibile"):
        value = importlib.import_module("trading_analyst").analyze_trading_chart(question)
        if value.get("successo"):
            memory.remember(
                str(value.get("messaggio", "")),
                kind="episodic",
                source="tradingview_analysis",
                confidence=0.8,
                importance=0.65,
                metadata={"question": question, "advisory_only": True},
            )
        return value

    registry.register(
        SkillManifest(
            "tradingview.snapshot",
            "1.0.0",
            "Read TradingView context without placing orders",
            ("tradingview context", "asset timeframe"),
            frozenset({Capability.BROWSER_CONTROL}),
            "applications:trading_snapshot",
        ),
        trading_snapshot,
    )
    registry.register(
        SkillManifest(
            "tradingview.analyze",
            "1.0.0",
            "Advisory-only visual TradingView analysis",
            ("analyze tradingview", "analizza grafico"),
            frozenset({Capability.READ_SCREEN}),
            "applications:trading_analyze",
        ),
        trading_analyze,
    )

    def football_analyze(snapshot: dict | None = None):
        data = dict(snapshot or {})
        if not data:
            browser = registry.execute("browser.snapshot")
            if browser.success:
                observed = dict(browser.data or {})
                url = str(observed.get("url") or "").casefold()
                if not any(domain in url for domain in importlib.import_module("football_analyst").BOOKMAKER_DOMAINS):
                    return {
                        "successo": False,
                        "messaggio": "Apri una pagina quote autorizzata di Snai, GoldBet o altro bookmaker supportato.",
                        "advisory_only": True,
                        "execution": {"bet_placement": False, "account_access": False},
                    }
                data = {
                    "source_context": " ".join(str(observed.get(key) or "") for key in ("title", "url", "text"))[
                        :12000
                    ],
                    "quotes": observed.get("quotes")
                    or importlib.import_module("football_analyst").extract_visible_quotes(
                        observed.get("text", ""), bookmaker=url.split("//", 1)[-1].split(".", 1)[0]
                    ),
                }
            else:
                return browser
        value = importlib.import_module("football_analyst").analyze_match(data)
        if value.get("successo"):
            value["messaggio"] = importlib.import_module("football_analyst").format_analysis(value)
            memory.remember(
                value["messaggio"],
                kind="episodic",
                source="football_analysis",
                confidence=0.65,
                importance=0.5,
                metadata={"advisory_only": True, "bet_placement": False},
            )
        return value

    registry.register(
        SkillManifest(
            "football.analyze",
            "1.0.0",
            "Advisory football match and odds analysis; never places bets",
            ("analizza partita", "analisi calcio", "quote partita", "pronostico calcio"),
            frozenset({Capability.BROWSER_CONTROL}),
            "applications:football_analyze",
            risk="safe",
            verification_strategy="structured_observation",
        ),
        football_analyze,
    )
