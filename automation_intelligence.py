"""Shared policy for choosing and evaluating desktop automations.

This is deliberately deterministic. The language model may propose a plan,
but this policy constrains the execution strategy and completion claims.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ActionMode(StrEnum):
    DIRECT = "direct"
    STRUCTURED_UI = "structured_ui"
    BROWSER_DOM = "browser_dom"
    OBSERVE_AND_ACT = "observe_and_act"
    ASK = "ask"


@dataclass(frozen=True, slots=True)
class AutomationPolicy:
    mode: ActionMode
    needs_observation: bool
    needs_verification: bool
    requires_clarification: bool
    reason: str


_DIRECT = re.compile(r"\b(apri|avvia|lancia|chiudi|imposta|alza|abbassa|metti|mostra|minimizza|massimizza)\b", re.I)
_UI = re.compile(r"\b(clicca|premi|seleziona|compila|scrivi|digita|campo|pulsante|finestra|schermo|mouse|tastiera)\b", re.I)
_BROWSER = re.compile(r"\b(browser|chrome|pagina|scheda|youtube|sito|web|risultato)\b", re.I)
_AMBIGUOUS = re.compile(r"\b(quello|quella|questo|questa|di prima|il primo|il secondo|l[iì]|fai così)\b", re.I)


def choose_policy(text: str, *, has_context: bool = False, has_fresh_observation: bool = False) -> AutomationPolicy:
    value = " ".join(str(text or "").split())
    if bool(_AMBIGUOUS.search(value)) and not has_context:
        return AutomationPolicy(ActionMode.ASK, False, False, True, "bersaglio ambiguo senza contesto verificabile")
    if _BROWSER.search(value):
        return AutomationPolicy(ActionMode.BROWSER_DOM, True, True, False, "pagina web: preferire DOM e snapshot fresco")
    if _UI.search(value):
        return AutomationPolicy(ActionMode.OBSERVE_AND_ACT, not has_fresh_observation, True, False, "azione su interfaccia: osservazione e prova obbligatorie")
    if _DIRECT.search(value):
        return AutomationPolicy(ActionMode.DIRECT, False, True, False, "capacità diretta con verifica dello stato finale")
    return AutomationPolicy(ActionMode.ASK, False, False, True, "obiettivo operativo non sufficientemente specifico")


def completion_allowed(result: dict, verification: dict | None) -> bool:
    """Never allow a successful final claim without structured evidence."""
    if not isinstance(result, dict) or not result.get("successo"):
        return False
    check = verification or {}
    return check.get("status") == "verified" and float(check.get("strength", 0)) >= 0.7


def policy_guidance() -> str:
    return (
        "AUTOMATION POLICY: scegli prima una capacità diretta; per UI usa UIA o DOM; "
        "usa visione solo se manca un controllo strutturato; usa mouse/tastiera solo "
        "con osservazione fresca e coordinate affidabili. Ogni azione deve avere una "
        "verifica indipendente. Non dichiarare completamento se la prova manca; "
        "chiedi chiarimento per riferimenti ambigui senza contesto."
    )
