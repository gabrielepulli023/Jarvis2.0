from __future__ import annotations
import importlib
from .state import PerceptionEngine, normalize_dom, normalize_uia, normalize_vision


def configure_default_observers(engine: PerceptionEngine) -> None:
    engine.register("dom", 300, lambda: importlib.import_module("chrome_bridge").chrome_snapshot(), normalize_dom)
    engine.register("uia", 200, lambda: importlib.import_module("desktop_intelligence").inspect_ui(), normalize_uia)

    def vision():
        result = importlib.import_module("vision").analizza_schermo()
        if result.get("successo") and not result.get("dati"):
            result = {**result, "dati": {"description": result.get("messaggio", "")}}
        return result

    engine.register("vision", 100, vision, normalize_vision)
