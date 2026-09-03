"""Deterministic intent and tool-strategy decision layer.

The LLM remains responsible for language understanding and tool arguments, but
this module supplies a stable policy envelope so every entry point agrees on
whether a request is conversational, informational, or an operation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from jarvis_core.cognitive_core import Decision, IntentKind, Strategy


@dataclass(frozen=True, slots=True)
class ControlIntent:
    """Central, backwards-compatible resolver for voice control intents."""

    name: str
    confidence: float
    reasons: tuple[str, ...] = ()


_MUTE = re.compile(
    r"\b(?:zitto|muto|muta|silenzia|smetti\s+di\s+ascoltare|non\s+ascoltarmi|"
    r"non\s+parlo\s+con\s+te|basta)\b",
    re.I,
)


def resolve_control_intent(text: str, *, addressed: bool = False, conversation_open: bool = False) -> ControlIntent | None:
    """Resolve semantic CONTROL families without exact-string matching.

    ``basta`` is intentionally accepted only with clear addressee evidence.
    """
    value = " ".join(str(text or "").casefold().split())
    if not value or not _MUTE.search(value):
        return None
    if "basta" in value and not addressed:
        return None
    if not addressed and not conversation_open:
        return None
    return ControlIntent("mute", 0.98 if addressed else 0.86, ("semantic_mute_family",))


_QUESTION = re.compile(r"^(?:chi|che|cosa|come|quando|dove|perch[eé]|quale|quali|quanto|puoi|riesci|è vero|mi spieghi)\b", re.I)
_ACTION = re.compile(r"^(?:per favore\s+)?(?:fammi|fai|fallo|usa|accedi|attiva|disattiva|crea|costruisci|sviluppa|apri|aprilo|aprila|chiudi|avvia|lancia|vai|scrivi|scrivilo|scrivila|digita|salva|salvalo|salvala|esporta|esportalo|esportala|metti|mettilo|mettila|sposta|copia|rinomina|elimina|rimuovi|installa|aggiorna|scarica|controlla|controllare|monitora|monitorare|tieni|avvisami|esegui|eseguire|gestisci|gestire|automatizza|configura|imposta|alza|abbassa|alzalo|abbassalo|muta|smuta|silenzia|spegni|riavvia|sospendi|blocca|premi|clicca|seleziona|mostra|nascondi|cattura|analizza|studia|converti|leggi|cerca|trova|recupera|recuperare|aggiungi|memorizza|memorizzare|inserisci|conserva|conservare|indicizza|invia|inviare|manda|mandare|modifica|modificare|genera|generare|compila|compilare|riproduci|riprodurre|archivia|archiviare|ordina|ordinare)\b", re.I)
_UI = re.compile(r"\b(mouse|tastiera|clicca|click|pulsante|finestra|schermo|pagina|scheda|menu|campo|scrivi|digita|seleziona|guarda|quello|webcam|microfono|youtube|browser|grafico|tradingview)\b", re.I)
_CONTEXT = re.compile(r"\b(continua|procedi|poi|ora|quello|quella|questo|questa|salvalo|salvala|aprilo|aprila|esportalo|esportala|mettilo|mettila|ripeti|di prima|lì|li|risultato|terzo|secondo|primo)\b", re.I)
_COMPLEX = re.compile(r"\b(e poi|poi|workflow|automatizza|organizza|piano|progetto completo|tutto|passo dopo passo)\b", re.I)
_DANGEROUS = re.compile(r"\b(elimina|cancella|spegni|riavvia|termina|installa|aggiorna|disinstalla|password|ordine|pagamento)\b", re.I)
_CAPABILITY = re.compile(r"\b(cosa sai fare|quali capacità|quali capacita|hai accesso|puoi controllare|sei in grado)\b", re.I)
_EXPANSION_TECHNOLOGY = re.compile(
    r"\b(?:qdrant|memoria\s+vettoriale|dxcam|docling|markitdown|crawl4ai|screenpipe|"
    r"watchdog|home\s+assistant|homeassistant|esphome|litellm|ollama|llama\.?cpp|"
    r"openhands|searxng|silero\s+vad|fastmcp|mcp|keyring|ruff)\b",
    re.I,
)


def _legacy_decide(text: str, *, has_context: bool = False) -> Decision:
    value = " ".join(str(text or "").strip().split())
    if not value:
        return Decision(IntentKind.CONVERSATION, Strategy.ASK_CLARIFICATION, 1.0, False, False, False, False, ("empty",))
    question = bool(_QUESTION.search(value)) or value.endswith("?")
    action = bool(_ACTION.search(value))
    ui = bool(_UI.search(value))
    context = bool(has_context and _CONTEXT.search(value))
    complex_request = bool(_COMPLEX.search(value))
    dangerous = bool(_DANGEROUS.search(value))
    expansion_request = bool(_EXPANSION_TECHNOLOGY.search(value)) and bool(
        re.search(
            r"\b(?:usa|usare|aggiungi|salva|salvare|memorizza|memorizzare|inserisci|conserva|"
            r"cerca|ricerca|trova|recupera|recuperare|analizza|converti|cattura|chiama|controlla|"
            r"esegui|eseguire|mostra|studia)\b",
            value,
            re.I,
        )
    )
    if expansion_request:
        action = True
    capability = bool(_CAPABILITY.search(value)) or (question and bool(re.search(r"\b(?:usare|controllare|accedere|gestire)\b", value, re.I)) and ui)
    affirmative_followup = bool(has_context and re.fullmatch(r"(?:s[iì]|si grazie|s[iì] grazie|ok|okay|va bene|certo|procedi|vai|fallo|fai pure|continua)", value, re.I))
    if affirmative_followup:
        action = True
        context = True
    # A bare knowledge search belongs to the conversational/research path.
    # Local files, web/browser navigation and explicit PC targets remain
    # operational requests.
    if action and re.match(r"^cerca\b", value, re.I) and not re.search(
        r"\b(?:file|cartella|documento|computer|pc|windows|desktop|disco|google|web|internet|browser|youtube)\b",
        value,
        re.I,
    ) and not _EXPANSION_TECHNOLOGY.search(value):
        action = False

    # A generic file search is an operation only when it names the local PC.
    if re.search(r"\b(?:file|cartella|documento)\b.*\b(?:computer|pc|windows|desktop|disco)\b", value, re.I):
        action = True

    if capability and not action:
        return Decision(IntentKind.CAPABILITY, Strategy.ANSWER, .98, False, False, False, False, ("capability_question",))
    if action and complex_request:
        return Decision(IntentKind.COMPOSITE, Strategy.PLAN_AND_VERIFY, .90, True, ui, context, dangerous, ("explicit_action", "multi_step"))
    if action:
        return Decision(IntentKind.OPERATION, Strategy.OBSERVE_THEN_ACT if ui else Strategy.USE_TOOLS, .92, True, ui, context, dangerous, ("explicit_action", "ui_signal" if ui else "direct_capability"))
    if ui and (question or context):
        return Decision(IntentKind.INFORMATION, Strategy.OBSERVE_THEN_ACT, .78, True, True, context, dangerous, ("screen_context_required",))
    if question:
        return Decision(IntentKind.INFORMATION, Strategy.ANSWER, .90, False, False, context, False, ("question_without_action",))
    return Decision(IntentKind.CONVERSATION, Strategy.ANSWER, .70, False, False, context, False, ("no_action_signal",))


def decide(text: str, *, has_context: bool = False) -> Decision:
    """Compatibility entry point backed by the canonical cognitive core."""
    from jarvis_core.cognitive_core import UnifiedCognitiveCore

    result = UnifiedCognitiveCore().decide(
        text,
        operational_context={} if has_context else None,
    )
    return Decision(
        result.intent_kind,
        result.strategy,
        result.confidence,
        result.needs_tools,
        result.needs_observation,
        result.needs_context,
        result.destructive,
        result.reasons,
    )


def router_guidance(decision: Decision) -> str:
    """Compact policy instruction injected into the model's current turn."""
    return (
        "DECISION LAYER: "
        f"kind={decision.kind.value}; strategy={decision.strategy.value}; "
        f"needs_tools={decision.needs_tools}; needs_observation={decision.needs_observation}; "
        f"needs_context={decision.needs_context}; destructive={decision.destructive}. "
        "Usa strumenti solo se servono al risultato; per UI preferisci DOM/UIA, "
        "poi osservazione, mouse/tastiera solo come ultima risorsa verificabile. "
        "Se la richiesta è una domanda senza azione, rispondi senza tool."
    )
