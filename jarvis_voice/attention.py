"""Selective attention and social conversation state for the shared voice path.

This module deliberately contains policy, not another audio or intent stack.  It
stores the social state through the existing StateManager when one is supplied.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AttentionState(StrEnum):
    IDLE = "idle"
    POSSIBLY_ADDRESSED = "possibly_addressed"
    ENGAGED = "engaged"
    CONVERSATION_OPEN = "conversation_open"
    DISENGAGED = "disengaged"
    MUTED = "muted"


@dataclass(frozen=True, slots=True)
class AttentionDecision:
    addressed: bool
    confidence: float
    reasons: tuple[str, ...]
    explicit_wake: bool = False


_OPERATION = re.compile(
    r"\b(?:apri|aprilo|aprila|chiudi|avvia|lancia|clicca|scrivi|digita|salva|cerca|"
    r"trova|mostra|nascondi|esegui|controlla|imposta|metti|alza|abbassa|riproduci|"
    r"invia|crea|sposta|copia|rinomina|elimina|muto|muta|silenzia)\b",
    re.I,
)
_REFERENCE = re.compile(r"\b(?:aprilo|aprila|quello|quella|questo|questa|lui|lei|di prima)\b", re.I)
_OTHER_PERSON = re.compile(r"\b(?:mamma|pap[aà]|mio padre|mia madre|lui|lei|ragazzi|guarda lui)\b", re.I)
_WAKE = re.compile(r"\b(?:jarvis|jarvi|iarvis|gervis|jarves)\b", re.I)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


class AttentionController:
    """Conservative addressedness gate and persistent mute state."""

    STATE_KEY = "conversation_attention"

    def __init__(self, state_manager=None, *, threshold: float = 0.72, clock=time.monotonic):
        self._state_manager = state_manager
        self.threshold = max(0.5, min(0.95, float(threshold)))
        self._clock = clock
        self._last_addressed_at = None
        self._state = self._read_state()

    def _read_state(self) -> AttentionState:
        if self._state_manager is not None:
            value = self._state_manager.get(self.STATE_KEY, {}).get("state")
            try:
                return AttentionState(value)
            except (TypeError, ValueError):
                pass
        return AttentionState.IDLE

    @property
    def state(self) -> AttentionState:
        return self._state

    def _set_state(self, value: AttentionState, *, reason: str = "") -> AttentionState:
        self._state = AttentionState(value)
        if self._state_manager is not None:
            self._state_manager.set(
                self.STATE_KEY,
                {"state": self._state.value, "reason": str(reason)[:80], "updated_monotonic": self._clock()},
                source="voice_attention",
            )
        return self._state

    def evaluate(
        self,
        text: str,
        *,
        explicit_wake: bool | None = None,
        conversation_open: bool = False,
        owner_speaker: bool | None = None,
        has_context: bool = False,
        activity_relevant: bool = False,
    ) -> AttentionDecision:
        value = _norm(text)
        wake = bool(_WAKE.search(value)) if explicit_wake is None else bool(explicit_wake)
        if wake:
            return AttentionDecision(True, 1.0, ("explicit_wake",), True)
        reasons: list[str] = []
        score = 0.0
        if conversation_open or self._state is AttentionState.CONVERSATION_OPEN:
            score += 0.32
            reasons.append("conversation_open")
        if owner_speaker is True:
            score += 0.22
            reasons.append("owner_speaker")
        elif owner_speaker is False:
            score -= 0.28
            reasons.append("unknown_or_non_owner_speaker")
        if _OPERATION.search(value):
            score += 0.30
            reasons.append("operational_intent")
        if has_context and _REFERENCE.search(value):
            score += 0.30
            reasons.append("resolvable_context_reference")
        if activity_relevant:
            score += 0.10
            reasons.append("relevant_activity")
        if _OTHER_PERSON.search(value) and not (conversation_open or has_context):
            score -= 0.65
            reasons.append("addressed_to_other_or_ambient")
        if not reasons:
            reasons.append("no_addressee_evidence")
        confidence = max(0.0, min(1.0, 0.5 + score / 2.0))
        addressed = confidence >= self.threshold
        self._set_state(
            AttentionState.POSSIBLY_ADDRESSED if not addressed and score > 0 else AttentionState.IDLE,
            reason=";".join(reasons),
        )
        if addressed:
            self._last_addressed_at = self._clock()
        return AttentionDecision(addressed, confidence, tuple(reasons), False)

    def enter_conversation(self) -> None:
        if self._state is not AttentionState.MUTED:
            self._set_state(AttentionState.CONVERSATION_OPEN, reason="conversation_started")

    def engage(self) -> None:
        if self._state is not AttentionState.MUTED:
            self._set_state(AttentionState.ENGAGED, reason="addressed_request")

    def disengage(self) -> None:
        if self._state is not AttentionState.MUTED:
            self._set_state(AttentionState.DISENGAGED, reason="conversation_closed")

    def mute(self) -> None:
        self._set_state(AttentionState.MUTED, reason="control_mute")

    def wake_from_mute(self) -> None:
        self._set_state(AttentionState.ENGAGED, reason="explicit_wake")

    def accepts(self, text: str, **signals: Any) -> AttentionDecision:
        if self._state is AttentionState.MUTED:
            if _WAKE.search(_norm(text)):
                return self.evaluate(text, **signals)
            return AttentionDecision(False, 0.0, ("muted",), False)
        return self.evaluate(text, **signals)
