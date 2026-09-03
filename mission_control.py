import re
from pathlib import Path


def build_plan(request):
    """Produce un piano iniziale compatto; il router può adattarlo durante la missione."""
    text = str(request or "").strip()
    lower = text.lower()
    steps = [{"id": "understand", "label": "Comprendere obiettivo e contesto", "status": "completed"}]
    if any(word in lower for word in ("crea", "costruisci", "sviluppa", "progetto", "bot", "sito")):
        steps.extend([
            {"id": "design", "label": "Progettare struttura e requisiti", "status": "pending"},
            {"id": "build", "label": "Creare gli artefatti", "status": "pending"},
            {"id": "inspect", "label": "Ispezionare il risultato", "status": "pending"},
            {"id": "test", "label": "Eseguire test e correggere errori", "status": "pending"},
        ])
    elif any(word in lower for word in ("chrome", "browser", "youtube", "tradingview", "schermo", "clicca")):
        steps.extend([
            {"id": "observe", "label": "Osservare applicazione e stato corrente", "status": "pending"},
            {"id": "act", "label": "Eseguire le interazioni necessarie", "status": "pending"},
            {"id": "verify", "label": "Verificare visivamente il risultato", "status": "pending"},
        ])
    else:
        clauses = [part.strip() for part in re.split(r"\b(?:e poi|poi|quindi|e)\b", text, flags=re.I) if part.strip()]
        for index, clause in enumerate(clauses[:8], 1):
            steps.append({"id": f"action_{index}", "label": clause[:180], "status": "pending"})
        steps.append({"id": "verify", "label": "Verificare il risultato finale", "status": "pending"})
    return steps


def verify_result(tool, arguments, result):
    """Verificatore indipendente e deterministico degli esiti degli strumenti."""
    value = dict(result or {})
    if not value.get("successo"):
        return {"status": "failed", "strength": 0.0, "evidence": str(value.get("messaggio") or "Errore dello strumento")[:500]}

    evidence = []
    data = value.get("dati") if isinstance(value.get("dati"), dict) else {}
    expansion_skill = str(value.get("skill") or arguments.get("skill") or "").strip()
    if tool == "expansion_call" and expansion_skill in {"qdrant.add", "qdrant.search"}:
        if data.get("verified") is not True:
            return {
                "status": "unverified",
                "strength": 0.0,
                "evidence": f"{expansion_skill} non ha fornito una prova verificabile",
            }
        evidence.append(str(data.get("verification_evidence") or f"{expansion_skill} ha restituito una prova verificata"))
    path_value = value.get("percorso") or data.get("path") or data.get("percorso")
    if path_value:
        path = Path(str(path_value))
        if path.exists():
            evidence.append(f"Percorso verificato: {path}")
        else:
            return {"status": "unverified", "strength": 0.35, "evidence": f"Percorso dichiarato ma non trovato: {path}"}

    visual_steps = data.get("passaggi")
    if tool == "visual_task":
        if isinstance(visual_steps, list):
            evidence.append(f"Ciclo visivo verificato in {len(visual_steps)} passaggi")
        else:
            return {"status": "unverified", "strength": 0.45, "evidence": "Esito visivo privo della cronologia di verifica"}

    if tool in {"inspect_project", "test_project"}:
        evidence.append("Controllo qualità completato senza errori")
    if not evidence:
        evidence.append(str(value.get("messaggio") or f"{tool} completato")[:500])
    strength = 1.0 if tool in {"visual_task", "inspect_project", "test_project"} or path_value else 0.75
    return {"status": "verified", "strength": strength, "evidence": "; ".join(evidence)}


def verified_success(result):
    """Return true only when a tool reports success and a verification proof."""
    value = dict(result or {})
    verification = value.get("verification")
    return bool(value.get("successo")) and isinstance(verification, dict) and verification.get("status") == "verified"


def completion_gate(steps):
    unresolved = {}
    uncertain = []
    for step in steps:
        check = step.get("verification", {})
        tool = step.get("tool", "unknown")
        if check.get("status") == "failed":
            unresolved[tool] = check
        elif check.get("status") == "verified":
            unresolved.pop(tool, None)
        elif check.get("status") == "unverified":
            uncertain.append(check)
    if unresolved:
        return "needs_attention", f"{len(unresolved)} errori non risolti"
    if uncertain:
        return "needs_verification", f"{len(uncertain)} passaggi da verificare"
    return "completed", "Tutti i passaggi eseguiti dispongono di una prova"
