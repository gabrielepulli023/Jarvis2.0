"""Bounded, local resolution of short conversational references.

This module is intentionally a resolver, not another context or memory store.
It reads and writes only the canonical runtime WorkingMemory and OperationalContext.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Mapping


CONVERSATION_TTL = 15 * 60.0
REFERENCE_TTL = 5 * 60.0
MAX_TEXT = 500
_PRONOUN = re.compile(r"\b(?:aprilo|aprila|chiudilo|chiudila|quello|quella|questo|questa|l'altro|l altro|il secondo|la seconda|quello di prima|di prima)\b", re.I)
_ORDINAL = re.compile(r"\b(?:il|la)\s+(primo|secondo|terzo|quarto|1|2|3|4)\b", re.I)
_OTHER = re.compile(r"\b(?:l[' ]altro|l[' ]altra)\b", re.I)
_CONTINUE = re.compile(r"^(?:continua|procedi|vai avanti|fallo|ok|s[iì])\W*$", re.I)
_WHY = re.compile(r"^(?:perch[eé]|come mai|e poi\??|cosa intendi\??|e invece quello\??)\W*$", re.I)
_PROPOSAL = re.compile(r"\b(?:posso|potrei|vuoi che|preferisci che)\b", re.I)
_APP_REQUEST = re.compile(r"\b(?:apri|avvia|lancia|chiudi)\s+(.+?)\s*(?:[.!?]|$)", re.I)
_SECRET = re.compile(r"(?i)(password|passphrase|api[_ -]?key|token|authorization|secret)\s*[:=]?\s*\S+")


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    resolved: bool
    reference_type: str | None = None
    value: Any = None
    confidence: float = 0.0
    source: str | None = None
    alternatives: tuple[Any, ...] = ()
    needs_clarification: bool = False
    clarification: str | None = None


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    text = _SECRET.sub(r"\1: [REDACTED]", str(value or ""))
    return " ".join(text.split())[:limit]


def _working(runtime) -> dict[str, Any]:
    memory = getattr(runtime, "memory", None)
    working = getattr(memory, "working", None)
    snapshot = getattr(working, "snapshot", None)
    return snapshot() if callable(snapshot) else {}


def _set(runtime, key: str, value: Any, ttl: float = CONVERSATION_TTL) -> None:
    working = getattr(getattr(runtime, "memory", None), "working", None)
    setter = getattr(working, "set", None)
    if callable(setter):
        setter(key, value, ttl=ttl)


def _conversation_snapshot(working: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in working.items():
        if not str(key).startswith("conversation."):
            continue
        leaf = str(key).split(".", 1)[1]
        if leaf in {"last_user_turn", "last_assistant_turn", "focus", "pending_question", "pending_proposal"}:
            result[leaf] = _clean(value)
        elif leaf in {"entities", "references", "last_action", "last_result", "active_object", "pending_choice"}:
            result[leaf] = value
    return result


def record_user_turn(runtime, text: str) -> None:
    """Record a compact volatile turn and deterministic candidate references."""
    value = _clean(text)
    if not value:
        return
    _set(runtime, "conversation.last_user_turn", value)
    _set(runtime, "conversation.focus", value, ttl=CONVERSATION_TTL)
    candidates: list[dict[str, str]] = []
    match = _APP_REQUEST.search(value)
    if match:
        raw = re.split(r"\s+e\s+|,", match.group(1), maxsplit=4, flags=re.I)
        for item in raw:
            name = _clean(item).strip(" .!?\"")
            if name and len(name) <= 80:
                candidates.append({"type": "application", "name": name})
    if candidates:
        _set(runtime, "conversation.references", candidates, ttl=REFERENCE_TTL)
        if len(candidates) == 1:
            _set(runtime, "conversation.active_object", candidates[0], ttl=REFERENCE_TTL)
        _set(runtime, "conversation.entities", [row["name"] for row in candidates], ttl=CONVERSATION_TTL)
    elif _WHY.match(value) or _CONTINUE.match(value):
        _set(runtime, "conversation.pending_question", value, ttl=REFERENCE_TTL)


def record_assistant_turn(runtime, text: str) -> None:
    value = _clean(text, 1000)
    if value:
        _set(runtime, "conversation.last_assistant_turn", value, ttl=CONVERSATION_TTL)
        if _PROPOSAL.search(value):
            record_assistant_proposal(runtime, value)


def record_assistant_proposal(runtime, proposal: str, *, focus: str | None = None) -> None:
    value = _clean(proposal, 800)
    if value:
        _set(runtime, "conversation.pending_proposal", value, ttl=REFERENCE_TTL)
        if focus:
            _set(runtime, "conversation.focus", _clean(focus), ttl=CONVERSATION_TTL)


def record_operational_action(runtime, request: str, result: Mapping[str, Any] | None) -> None:
    """Retain only a small verified action reference; full result stays operational."""
    data = result if isinstance(result, Mapping) else {}
    verified = bool(data.get("successo")) and (
        data.get("verification", {}).get("status") == "verified"
        if isinstance(data.get("verification"), Mapping)
        else bool(data.get("dati", {}).get("verified")) if isinstance(data.get("dati"), Mapping) else False
    )
    if not verified:
        return
    request_value = _clean(request)
    _set(runtime, "conversation.last_action", {"request": request_value, "verified": True}, ttl=REFERENCE_TTL)
    match = _APP_REQUEST.search(request_value)
    if match:
        name = _clean(match.group(1)).strip(" .!?\"")
        if name:
            active = {"type": "application", "name": name, "action": request_value.split()[0].casefold(), "verified": True}
            _set(runtime, "conversation.active_object", active, ttl=REFERENCE_TTL)


class ReferenceResolver:
    """Resolve only fresh, local candidates; ambiguity is never guessed."""

    def __init__(self, runtime, *, clock=time.monotonic):
        self.runtime = runtime
        self.clock = clock

    def _operational(self) -> Mapping[str, Any] | None:
        context = getattr(self.runtime, "context", None)
        getter = getattr(context, "operational_context", None)
        value = getter() if callable(getter) else None
        return value if isinstance(value, Mapping) else None

    def resolve(self, text: str) -> ReferenceResolution:
        value = " ".join(str(text or "").casefold().split())
        if not value:
            return ReferenceResolution(False)
        working = _working(self.runtime)
        operational = self._operational()
        if _PRONOUN.search(value) and operational and operational.get("status") == "succeeded":
            path = operational.get("artifact_path") or operational.get("source_path")
            if path and re.search(r"\b(?:aprilo|aprila|quello|quella|questo|questa)\b", value):
                return ReferenceResolution(True, "artifact/result", str(path), .98, "operational_context")
        refs = working.get("conversation.references")
        refs = [row for row in refs if isinstance(row, Mapping) and row.get("name")] if isinstance(refs, list) else []
        if _ORDINAL.search(value):
            word = _ORDINAL.search(value).group(1).casefold()
            index = {"primo": 0, "secondo": 1, "terzo": 2, "quarto": 3, "1": 0, "2": 1, "3": 2, "4": 3}.get(word)
            if index is not None and index < len(refs):
                return ReferenceResolution(True, str(refs[index].get("type") or "entity"), refs[index], .95, "working_memory")
        if _OTHER.search(value):
            if len(refs) == 2:
                active = working.get("conversation.active_object")
                other = next((row for row in refs if row != active), None)
                if other:
                    return ReferenceResolution(True, str(other.get("type") or "entity"), other, .9, "working_memory")
            return self._ambiguous(refs)
        if _PRONOUN.search(value):
            active = working.get("conversation.active_object")
            if isinstance(active, Mapping) and active.get("name") and len(refs) <= 1:
                return ReferenceResolution(True, str(active.get("type") or "entity"), active, .9, "working_memory")
            if len(refs) > 1:
                return self._ambiguous(refs)
            snapshot = getattr(getattr(self.runtime, "context", None), "snapshot", lambda: {})()
            opened = snapshot.get("opened_apps", []) if isinstance(snapshot, Mapping) else []
            candidates = [
                {"type": "application", "name": _clean(row.get("name") or row.get("executable"))}
                for row in opened
                if isinstance(row, Mapping) and (row.get("name") or row.get("executable"))
            ]
            candidates = [row for row in candidates if row["name"]]
            if len(candidates) == 1:
                return ReferenceResolution(True, "application", candidates[0], .84, "runtime_context")
            if len(candidates) > 1:
                return self._ambiguous(candidates[:8])
        if _CONTINUE.match(value) or _WHY.match(value):
            focus = working.get("conversation.focus") or working.get("conversation.last_assistant_turn")
            if focus:
                return ReferenceResolution(True, "conversational entity/topic", _clean(focus), .82, "working_memory")
        return ReferenceResolution(False)

    @staticmethod
    def _ambiguous(candidates: list[Mapping[str, Any]]) -> ReferenceResolution:
        names = tuple(_clean(row.get("name")) for row in candidates)
        question = " o ".join(names) if names else None
        return ReferenceResolution(False, "application", None, .2, "working_memory", names, True, question)


def resolve_reference(runtime, text: str) -> ReferenceResolution:
    return ReferenceResolver(runtime).resolve(text)


def compact_current_context(runtime, *, max_chars: int = 1800) -> str:
    """Render a small redacted context block for AI/router consumers."""
    working = _working(runtime)
    conversation = _conversation_snapshot(working)
    operational = getattr(getattr(runtime, "context", None), "operational_context", lambda: None)()
    rows = []
    for label, key in (("focus", "focus"), ("ultimo turno JARVIS", "last_assistant_turn"), ("oggetto attivo", "active_object"), ("ultimi riferimenti", "references"), ("proposta pending", "pending_proposal")):
        if conversation.get(key):
            rows.append(f"- {label}: {_clean(conversation[key], 500)}")
    if isinstance(operational, Mapping) and operational.get("status") == "succeeded":
        artifact = operational.get("artifact_path") or operational.get("source_path")
        if artifact:
            rows.append(f"- risultato operativo verificato: {_clean(artifact, 300)}")
    context = getattr(runtime, "context", None)
    snapshot = context.snapshot() if callable(getattr(context, "snapshot", None)) else {}
    active = snapshot.get("active_window") if isinstance(snapshot, Mapping) else None
    if isinstance(active, Mapping) and active.get("title"):
        rows.append(f"- finestra attiva: {_clean(active['title'], 300)}")
    return "\n".join(rows)[:max(256, int(max_chars))]


def conversation_snapshot(working: Mapping[str, Any]) -> dict[str, Any]:
    return _conversation_snapshot(working)
