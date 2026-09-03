from pathlib import Path

from action_guard import HIGH_RISK, risk_level


def simulate_action(tool, arguments):
    args = dict(arguments or {})
    warnings = []
    reversible = tool not in {"spegni_pc", "riavvia_pc", "sospendi_pc", "termina_processo", "installa_programma"}
    for key in ("percorso", "destinazione", "origine"):
        value = args.get(key)
        if value:
            try:
                path = Path(str(value)).resolve()
                if any(part.lower() in {"windows", "program files", "program files (x86)"} for part in path.parts):
                    warnings.append(f"Percorso protetto: {path}")
            except Exception:
                warnings.append(f"Percorso non risolvibile: {value}")
    if tool in HIGH_RISK:
        warnings.append("Azione ad alto impatto")
    return {
        "successo": not warnings,
        "messaggio": "Simulazione completata senza criticità." if not warnings else "Simulazione completata con avvisi.",
        "dati": {"tool": tool, "arguments": args, "risk": risk_level(tool), "reversible": reversible, "warnings": warnings, "executed": False},
    }
