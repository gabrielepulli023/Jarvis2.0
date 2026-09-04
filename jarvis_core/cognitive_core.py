"""Canonical, local cognitive decision boundary for JARVIS.

This module only classifies and ranks.  It never executes tools, calls a
provider, observes hardware, or mutates the World Model as a side effect.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from jarvis_core.logging import redact
from mission_control import build_plan


class IntentKind(StrEnum):
    CONVERSATION = "conversation"
    INFORMATION = "information"
    CAPABILITY = "capability"
    OPERATION = "operation"
    COMPOSITE = "composite"
    CONTROL = "control"


class Strategy(StrEnum):
    ANSWER = "answer"
    ASK_CLARIFICATION = "ask_clarification"
    USE_TOOLS = "use_tools"
    OBSERVE_THEN_ACT = "observe_then_act"
    PLAN_AND_VERIFY = "plan_and_verify"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: IntentKind
    strategy: Strategy
    confidence: float
    needs_tools: bool
    needs_observation: bool
    needs_context: bool
    destructive: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CognitiveDecision:
    intent_kind: IntentKind
    strategy: Strategy
    semantic_action: str | None = None
    target: str | None = None
    target_type: str | None = None
    original_user_text: str = ""
    resolved_operational_text: str = ""
    needs_tools: bool = False
    needs_observation: bool = False
    needs_context: bool = False
    needs_clarification: bool = False
    clarification: str | None = None
    mission_required: bool = False
    destructive: bool = False
    risk_hint: str = "safe"
    candidate_skills: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    confidence: float = 0.0
    confidence_components: Mapping[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    resolved_reference: Any = None
    world_support: Mapping[str, Any] = field(default_factory=dict)
    context_support: Mapping[str, Any] = field(default_factory=dict)
    negated: bool = False

    @property
    def kind(self):
        return self.intent_kind

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["intent_kind"] = self.intent_kind.value
        value["strategy"] = self.strategy.value
        return redact(value)


_ACTION_FAMILIES = {
    "open": r"apr\w*|apri\w*|lanci\w*|avvi\w*|parti\w*|start\w*|fammi\s+partire",
    "close": r"chiud\w*|termin\w*|fai\s+fuori",
    "read": r"legg\w*|mostr\w*|visualizz\w*",
    "write": r"scriv\w*|digit\w*|salv\w*|inserisc\w*",
    "search": r"cerc\w*|trova\w*|ricerc\w*",
    "create": r"cre\w*|gener\w*|costruisc\w*|svilupp\w*",
    "delete": r"elimin\w*|cancell\w*|rimuov\w*",
    "control": r"alz\w*|abbass\w*|impost\w*|spost\w*|copi\w*|clicc\w*|prem\w*|selezion\w*|spegni\w*|riavvi\w*|acced\w*|gestisc\w*|controlla\w*|verific\w*|us\w*",
    "manage": r"invi\w*|modific\w*|riproduc\w*|aggiung\w*|memorizz\w*|inserisc\w*|conserv\w*|archivi\w*|indicizz\w*|recuper\w*|automatizz\w*|organizz\w*|corregg\w*|test(?:a|alo|are|i|ando)\w*",
    "observe": r"guard\w*|osserv\w*|mostr\w*|visualizz\w*",
}
_ACTION_RE = re.compile(r"\b(?:" + "|".join(_ACTION_FAMILIES.values()) + r")\b", re.I)
_EXPLANATION_RE = re.compile(r"\b(?:come\s+si|come\s+faccio|come\s+potrei|come\s+(?:si\s+)?(?:apr\w*|chiud\w*|avvi\w*|lanci\w*)|mi\s+spiegh\w*|spieg\w*|spiegami|volevo\s+sapere|cosa\s+succede\s+se|[eè]\s+possibile)\b", re.I)
_NEGATION_RE = re.compile(r"\b(?:non|mai|senza)\b", re.I)
_CAPABILITY_RE = re.compile(r"\b(?:cosa\s+sai\s+fare|quali\s+capacit|hai\s+accesso|puoi\s+(?:usare|controllare|gestire))\b", re.I)
_COMPOSITE_RE = re.compile(r"\b(?:e\s+poi|poi|quindi|dopo|workflow|progetto\s+completo|passo\s+passo|tutto)\b", re.I)
_DANGEROUS_RE = re.compile(r"\b(?:elimin\w*|cancell\w*|spegni|riavvi\w*|install\w*|aggiorna|disinstall\w*)\b", re.I)
_UI_RE = re.compile(r"\b(?:mouse|tastiera|clicc\w*|pulsante|finestra|schermo|pagina|scheda|menu|campo|webcam|microfono|quello|quella|questo|questa)\b", re.I)
_MISSION_RE = re.compile(r"\b(?:e\s+poi|poi|quindi|dopo|workflow|progetto\s+completo|passo\s+passo|tutto|test\w*|corregg\w*|organizz\w*|automatizz\w*)\b", re.I)


def _normalize(value: Any) -> str:
    from jarvis_skills.registry import normalize_trigger_text
    return normalize_trigger_text(value)


def _stem(token: str) -> str:
    return token[: max(4, min(7, len(token)))]


_APP_ACTION_RE = re.compile(
    r"\b(?:" + _ACTION_FAMILIES["open"] + r"|" + _ACTION_FAMILIES["close"] + r")\b", re.I
)
_CLAUSE_ACTION_RE = re.compile(r"\b(?:esegui\w*|" + "|".join(_ACTION_FAMILIES.values()) + r")\b", re.I)
_TARGET_WRAPPER_RE = re.compile(r"^(?:il|lo|la|i|gli|le|un|una|uno)\s+", re.I)


def _extract_application_target(text: str) -> str | None:
    """Extract a generic app name after an explicit open/close verb."""
    match = _APP_ACTION_RE.search(text)
    if not match:
        return None
    candidate = text[match.end():].strip(" \t.,!?;:")
    for boundary in re.finditer(r",|\s+(?:e\s+poi|poi|quindi|dopo)\s+|\s+e\s+", candidate, re.I):
        if _CLAUSE_ACTION_RE.match(candidate[boundary.end():].lstrip()):
            candidate = candidate[:boundary.start()].rstrip(" \t.,!?;:")
            break
    candidate = re.sub(r"^(?:mi|m[iì]|per\s+favore)\s+", "", candidate, flags=re.I)
    candidate = _TARGET_WRAPPER_RE.sub("", candidate).strip(" \t.,!?;:")
    candidate = re.sub(r"\s+per\s+favore$", "", candidate, flags=re.I).strip(" \t.,!?;:")
    if not candidate or len(candidate) > 120 or re.search(r"\b(?:come|perch[eé]|cosa|se|spiegami|potresti|puoi)\b", candidate, re.I):
        return None
    return candidate


class UnifiedCognitiveCore:
    """Single owner for semantic intent, confidence and decision policy."""

    HIGH = 0.82
    MEDIUM = 0.60

    def __init__(self, *, registry=None, context=None, world=None, memory=None, state=None, events=None, clock=time.monotonic):
        self.registry = registry
        self.context = context
        self.world = world
        self.memory = memory
        self.state = state
        self.events = events
        self.clock = clock
        self._last: CognitiveDecision | None = None

    def _reference_target(self, reference):
        if not reference or not getattr(reference, "resolved", False):
            return None
        value = getattr(reference, "value", None)
        if isinstance(value, Mapping):
            return str(value.get("name") or value.get("path") or value.get("title") or "") or None
        return str(value or "") or None

    def _rank_skills(self, text: str, action: str | None) -> list[tuple[str, float]]:
        if self.registry is None:
            return []
        normalized = _normalize(text)
        tokens = set(normalized.split())
        stems = {_stem(token) for token in tokens}
        ranked: list[tuple[str, float]] = []
        for row in self.registry.list():
            best = 0.0
            for intent in row.get("intents", ()):
                intent_tokens = set(_normalize(intent).split())
                if not intent_tokens:
                    continue
                exact = _normalize(intent) in normalized
                overlap = len(tokens & intent_tokens) / len(intent_tokens)
                stem_overlap = len(stems & {_stem(token) for token in intent_tokens}) / len(intent_tokens)
                score = 1.0 if exact else max(overlap, stem_overlap * 0.9)
                best = max(best, score)
            if best >= 0.55:
                ranked.append((str(row.get("name")), best * float(row.get("confidence", 1.0))))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:8]

    def _target_type(self, target: str | None, action: str | None, reference=None) -> str | None:
        reference_type = str(getattr(reference, "reference_type", "") or "").casefold()
        if reference_type in {"artifact", "path", "file", "result"}:
            return "artifact"
        if target and (re.match(r"^(?:file|cartella|documento)\b", target, re.I) or re.search(r"[\\/:]", target) or re.search(r"\.(?:txt|pdf|docx?|xlsx?|csv|json|py|zip)\b", target, re.I)):
            return "artifact"
        if action in {"observe"} or (target and _UI_RE.search(target)):
            return "ui"
        if target and re.search(r"\b(?:pc|computer|windows|sistema|volume|audio|schermo)\b", target, re.I):
            return "system"
        if target and re.search(r"\b(?:chrome|spotify|firefox|edge|youtube|google|blocco note|calcolatrice|qdrant)\b", target, re.I):
            return "application"
        if target and action in {"open", "close"}:
            return "application"
        return "generic" if target else None

    def _world_support(self, target: str | None, target_type: str | None, action: str | None) -> dict[str, Any]:
        if not target or target_type not in {"application", "artifact", "ui"} or self.world is None:
            return {}
        try:
            entity = self.world.get(f"{target_type}:{target}")
        except Exception:
            entity = None
        if not entity:
            return {}
        properties = entity.get("properties", {})
        return {"target": target, "action": action, "evidence": properties.get("running") or properties.get("focused")}

    @staticmethod
    def _mission_required(text: str, action: str | None, *, informative: bool = False) -> bool:
        """Shared semantic mission policy for the core and legacy facade."""
        if informative or not action:
            return False
        return len(_ACTION_RE.findall(text)) > 1 or bool(_MISSION_RE.search(text))

    def decide(self, original_user_text: str, *, resolved_operational_text: str | None = None, reference=None, operational_context=None, attention=None) -> CognitiveDecision:
        original = " ".join(str(original_user_text or "").strip().split())[:2000]
        text = " ".join(str(resolved_operational_text or original).strip().split())[:2000]
        has_context = bool(reference and getattr(reference, "resolved", False)) or operational_context is not None
        action_match = _ACTION_RE.search(text)
        action = None
        if action_match:
            for name, pattern in _ACTION_FAMILIES.items():
                if re.search(r"\b(?:" + pattern + r")\b", text, re.I):
                    action = name
                    break
        if not action and has_context and re.search(r"\b(?:guard\w*|quello|quella|questo|questa)\b", text, re.I):
            action = "observe"
        if action == "observe" and not has_context:
            action = None
        explanation = bool(_EXPLANATION_RE.search(text))
        negated = bool(_NEGATION_RE.search(text)) and bool(action)
        capability = bool(_CAPABILITY_RE.search(text))
        capability_request = capability and bool(re.search(r"\b(?:puoi\s+usare|hai\s+accesso|cosa\s+sai\s+fare|quali\s+capacit)\b", text, re.I))
        statement = bool(re.match(r"^(?:ho|hai|abbiamo|hanno|sto|stavo|vorrei sapere)\b", text, re.I))
        target = self._reference_target(reference)
        question = text.endswith("?")
        informative = explanation or statement or (question and not capability and not action)
        if not target and action in {"open", "close"} and not informative and not negated:
            target = _extract_application_target(text)
        if not target and action:
            target_match = re.search(r"(?:[A-Za-z]:[\\/][^\s,?]+|\b[\w.-]+\.(?:txt|pdf|docx?|xlsx?|csv|json|py|zip)\b|\b(?:Chrome|Spotify|Firefox|Edge|YouTube|Google|Qdrant|Keyring|Blocco Note|calcolatrice|file|cartella|computer|PC|documento|messaggio|video|segreto|password)\b)", text, re.I)
            target = target_match.group(0) if target_match else None
        if not target and action:
            candidate = re.sub(r"^(?:per favore|mi|puoi|potresti|riesci|fammi|fai|devi|vorrei)\s+", "", text, flags=re.I)
            candidate = re.sub(r"^(?:\w+\s+){1,2}", "", candidate) if action in {"open", "close", "delete", "search"} else candidate
            target_match = re.search(r"(?:[A-Za-z]:[\\/][^\s,?]+|\b[\w.-]+\.(?:txt|pdf|docx?|xlsx?|csv|json|py|zip)\b|\b(?:Chrome|Spotify|Firefox|Edge|YouTube|Google|Qdrant|Keyring|Blocco Note|calcolatrice|file|cartella|computer|PC|documento|messaggio|video|segreto|password)\b)", candidate, re.I)
            target = target_match.group(0) if target_match else None
        if action == "search" and not target and not re.search(r"\b(?:web|internet|google|youtube|qdrant|memoria|file|cartella|documento|computer|pc)\b", text, re.I):
            action = None
        ranked = self._rank_skills(text, action)
        candidate_skills = tuple(name for name, _score in ranked)
        top_score = ranked[0][1] if ranked else (0.92 if action else 0.0)
        alternatives = tuple(name for name, score in ranked[1:3] if top_score - score < 0.12)
        ambiguous = bool(alternatives and top_score - ranked[1][1] < 0.08)
        mission = self._mission_required(text, action, informative=informative)
        composite = bool(mission)
        if capability_request:
            kind, strategy, needs_tools = IntentKind.CAPABILITY, Strategy.ANSWER, False
        elif informative or explanation or (action and explanation) or statement:
            kind, strategy, needs_tools = IntentKind.INFORMATION, Strategy.ANSWER, False
        elif negated:
            kind, strategy, needs_tools = IntentKind.INFORMATION, Strategy.ANSWER, False
        elif action:
            kind = IntentKind.COMPOSITE if mission else IntentKind.OPERATION
            strategy = Strategy.PLAN_AND_VERIFY if mission else Strategy.OBSERVE_THEN_ACT if (_UI_RE.search(text) and not (action == "search" and target)) else Strategy.USE_TOOLS
            needs_tools = True
        else:
            kind, strategy, needs_tools = IntentKind.CONVERSATION, Strategy.ANSWER, False
        needs_clarification = bool(needs_tools and (not target and action in {"open", "close", "delete", "write", "search"})) or ambiguous
        if needs_clarification:
            strategy = Strategy.ASK_CLARIFICATION
            needs_tools = False
        target_type = self._target_type(target, action, reference)
        world_support = self._world_support(target, target_type, action)
        context_support = {"reference": bool(reference and getattr(reference, "resolved", False)), "operational": bool(operational_context)}
        components = {"intent": 0.96 if action or informative else 0.70}
        if ranked:
            components["skill_match"] = min(1.0, top_score)
        if reference and getattr(reference, "resolved", False):
            components["reference"] = float(getattr(reference, "confidence", 0.86) or 0.86)
        elif target:
            components["target"] = 0.95
        evidence = world_support.get("evidence")
        if isinstance(evidence, Mapping):
            components["world"] = float(evidence.get("confidence", 0.0) or 0.0)
        if attention is not None:
            components["attention"] = max(0.0, min(1.0, float(attention)))
        confidence = sum(components.values()) / max(1, len(components))
        if informative or capability:
            confidence = max(confidence, 0.86)
        if needs_clarification or negated:
            confidence = min(confidence, 0.58)
        if needs_tools and confidence < self.MEDIUM:
            needs_clarification, needs_tools, strategy = True, False, Strategy.ASK_CLARIFICATION
        elif needs_tools and confidence < self.HIGH and not target and not candidate_skills:
            needs_clarification, needs_tools, strategy = True, False, Strategy.ASK_CLARIFICATION
        risk = "destructive" if _DANGEROUS_RE.search(text) else "safe"
        decision = CognitiveDecision(kind, strategy, action, target, target_type, original, text, needs_tools, bool(action and _UI_RE.search(text) and not explanation), has_context, needs_clarification, "Quale bersaglio intendi?" if needs_clarification else None, mission, risk == "destructive", risk, candidate_skills, alternatives, max(0.0, min(1.0, confidence)), components, tuple(("negation" if negated else "explanation" if explanation else "composite_request" if composite else "explicit_action" if action else "question_or_conversation",)), getattr(reference, "value", None) if reference else None, world_support, context_support, negated)
        self._last = decision
        return decision

    def snapshot(self) -> dict[str, Any]:
        return self._last.to_dict() if self._last else {"available": True, "last_decision": None}

    def explain_last(self) -> dict[str, Any] | None:
        return self._last.to_dict() if self._last else None


def mission_required(text: str) -> bool:
    value = " ".join(str(text or "").split())
    action = _ACTION_RE.search(value)
    informative = bool(_EXPLANATION_RE.search(value) or (value.endswith("?") and not action))
    return UnifiedCognitiveCore._mission_required(value, action.group(0) if action else None, informative=informative)


def _json(raw):
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    return json.loads(text)


def plan_mission(client, model, objective, context=""):
    fallback = build_plan(objective)
    try:
        response = client.responses.create(model=model, instructions="Sei il pianificatore di Mission Control. Produci solo JSON valido.", input=f"Obiettivo: {objective}\nContesto operativo: {context}\nGenera un piano adattivo di massimo 10 passaggi.", reasoning={"effort": "medium"})
        data = _json(response.output_text)
        steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(steps, list) or not steps:
            raise ValueError("Piano vuoto")
        return {"goal": str(data.get("goal") or objective)[:1000], "success_criteria": [str(x)[:300] for x in data.get("success_criteria", [])[:8]], "steps": steps[:10], "risks": [str(x)[:300] for x in data.get("risks", [])[:8]], "source": "planner"}
    except Exception as exc:
        return {"goal": str(objective), "success_criteria": ["Risultato finale verificato"], "steps": fallback, "risks": [], "source": "fallback", "planner_error": redact(repr(exc))}


def review_mission(client, model, objective, plan, executed_steps, proposed_summary):
    evidence = [{"tool": step.get("tool"), "success": step.get("success"), "message": step.get("message"), "verification": step.get("verification")} for step in executed_steps[-30:]]
    try:
        response = client.responses.create(model=model, instructions="Sei il critico indipendente di JARVIS. Produci solo JSON valido.", input=json.dumps({"objective": objective, "plan": plan, "evidence": evidence, "proposed_summary": proposed_summary}, ensure_ascii=False), reasoning={"effort": "medium"})
        data = _json(response.output_text)
        return {"complete": bool(data.get("complete")), "confidence": max(0.0, min(float(data.get("confidence", 0)), 1.0)), "missing": [str(x)[:400] for x in data.get("missing", [])[:8]], "next_action": str(data.get("next_action") or "")[:800], "summary": str(data.get("summary") or proposed_summary)[:2000]}
    except Exception as exc:
        deterministic_ok = bool(executed_steps) and all(step.get("verification", {}).get("status") == "verified" for step in executed_steps)
        return {"complete": deterministic_ok, "confidence": 0.7 if deterministic_ok else 0.2, "missing": [] if deterministic_ok else ["Verifica critica non disponibile"], "next_action": "Verifica nuovamente il risultato", "summary": proposed_summary, "critic_error": redact(repr(exc))}
