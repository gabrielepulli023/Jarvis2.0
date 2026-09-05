"""Deterministic conversational style selection.

This module is deliberately not a planner, memory store, sentiment tracker or
action policy.  It only returns bounded presentation hints for one response.
"""
from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from settings_store import get_setting, set_setting


_FIELDS = ("warmth", "humor", "sarcasm", "formality", "directness", "verbosity", "empathy", "confidence_style")


@dataclass(frozen=True, slots=True)
class PersonalityProfile:
    warmth: float = 0.55
    humor: float = 0.28
    sarcasm: float = 0.12
    formality: float = 0.42
    directness: float = 0.82
    verbosity: float = 0.32
    empathy: float = 0.55
    confidence_style: float = 0.78


@dataclass(frozen=True, slots=True)
class ResponseStyle:
    signal: str
    warmth: float
    humor: float
    sarcasm: float
    formality: float
    directness: float
    verbosity: float
    empathy: float
    confidence_style: float
    high_stakes: bool = False


_SIGNALS = {
    "urgent": re.compile(r"\b(urgente|subito|ora|emergenza|emergency|presto|bloccato)\b", re.I),
    "frustrated": re.compile(r"(non funziona(?!.*\b(traceback|python|codice)\b)|di nuovo|basta|che rabbia|sono stanco|frustrat|te l'ho già detto|non hai capito)", re.I),
    "technical": re.compile(r"\b(api|python|codice|debug|stack|traceback|json|database|configur|implement|test)", re.I),
    "serious": re.compile(r"\b(grave|serio|sicurezza|privacy|rischio|pericolo|crisi|perdita)", re.I),
    "supportive": re.compile(r"\b(aiutami|ho bisogno|preoccup|ansia|difficile|non so cosa fare)", re.I),
    "celebratory": re.compile(r"\b(ottimo|perfetto|ce l'abbiamo|riuscit|evviva|fantastico|grazie)", re.I),
    "casual": re.compile(r"\b(ciao|hey|ehi|come va|senti|dai|ok|grazie)", re.I),
}
_HIGH_STAKES = re.compile(
    r"(autorizz|permess|conferm|emergenz|sicurezza|privacy|password|segreto|irrevers|elimin|ordine|trading|finanz|hardware|missione critica|rischio)", re.I
)


class PersonalityEngine:
    """Owns one stable profile and produces no operational side effects."""

    def __init__(self, *, settings_get=get_setting, settings_set=set_setting):
        self._get = settings_get
        self._set = settings_set
        self._lock = threading.RLock()
        self._mutation_lock = threading.Lock()
        self._profile = self._load_profile()

    @staticmethod
    def default_profile() -> PersonalityProfile:
        return PersonalityProfile()

    @staticmethod
    def _bounded(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    def _validated(self, values: Mapping[str, Any], base: PersonalityProfile | None = None) -> PersonalityProfile:
        current = base or self.default_profile()
        return replace(current, **{key: self._bounded(values.get(key, getattr(current, key)), getattr(current, key)) for key in _FIELDS})

    def _load_profile(self) -> PersonalityProfile:
        stored = self._get("personality_profile", {})
        return self._validated(stored if isinstance(stored, Mapping) else {})

    def profile(self) -> PersonalityProfile:
        with self._lock:
            return self._profile

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"profile": asdict(self._profile), "signals": (), "raw_text": None}

    def update(self, preferences: Mapping[str, Any]) -> PersonalityProfile:
        if not isinstance(preferences, Mapping):
            raise TypeError("preferences must be a mapping")
        allowed = {str(key): value for key, value in preferences.items() if str(key) in _FIELDS}
        with self._mutation_lock:
            with self._lock:
                candidate = self._validated(allowed, self._profile)
            # Persistence is serialized, but never performed while _lock is held.
            self._set("personality_profile", asdict(candidate))
            with self._lock:
                self._profile = candidate
                return candidate

    def reset(self) -> PersonalityProfile:
        with self._mutation_lock:
            candidate = self.default_profile()
            self._set("personality_profile", asdict(candidate))
            with self._lock:
                self._profile = candidate
                return candidate

    def classify(self, text: str) -> str:
        bounded = str(text or "")[:1000]
        for signal in ("urgent", "frustrated", "technical", "serious", "supportive", "celebratory", "casual"):
            if _SIGNALS[signal].search(bounded):
                return signal
        return "normal"

    def select_style(self, text: str = "", *, cognitive_decision=None, context: Mapping[str, Any] | None = None,
                     system_state: Mapping[str, Any] | None = None, memory_hint: Mapping[str, Any] | None = None,
                     structured_metadata: Mapping[str, Any] | None = None) -> ResponseStyle:
        del context, system_state, memory_hint  # volatile hints never become persisted personality state
        with self._lock:
            profile = self._profile
        signal = self.classify(text)
        values = asdict(profile)
        if signal == "casual": values.update(warmth=min(1, values["warmth"] + .12), humor=min(1, values["humor"] + .12))
        elif signal == "technical": values.update(directness=min(1, values["directness"] + .12), formality=min(1, values["formality"] + .10), humor=max(0, values["humor"] - .12))
        elif signal == "urgent": values.update(directness=1.0, verbosity=max(0, values["verbosity"] - .18), humor=0.0, sarcasm=0.0)
        elif signal == "frustrated": values.update(warmth=min(1, values["warmth"] + .08), empathy=min(1, values["empathy"] + .18), directness=min(1, values["directness"] + .10), sarcasm=0.0)
        elif signal == "serious": values.update(formality=min(1, values["formality"] + .15), humor=0.0, sarcasm=0.0)
        elif signal == "supportive": values.update(warmth=min(1, values["warmth"] + .15), empathy=min(1, values["empathy"] + .15), sarcasm=0.0)
        elif signal == "celebratory": values.update(warmth=min(1, values["warmth"] + .10), humor=min(1, values["humor"] + .08))
        decision_risk = str(getattr(cognitive_decision, "risk_hint", "")).lower()
        metadata_risk = str((structured_metadata or {}).get("risk", "")).lower()
        # Canonical structured risk wins over lexical hints; personality never
        # derives or changes the risk itself.
        structured_high_stakes = decision_risk in {"critical", "high", "destructive", "admin"} or metadata_risk in {"critical", "high", "destructive", "admin"} or bool(getattr(cognitive_decision, "destructive", False))
        high_stakes = structured_high_stakes or bool(_HIGH_STAKES.search(str(text or "")[:1000]))
        if high_stakes:
            values["humor"] = values["sarcasm"] = 0.0
        bounded = self._validated(values)
        return ResponseStyle(signal=signal, high_stakes=high_stakes, **asdict(bounded))

    def prompt_fragment(self, text: str = "", *, cognitive_decision=None) -> str:
        style = self.select_style(text, cognitive_decision=cognitive_decision)
        return ("Stile conversazionale corrente (solo presentazione): "
                f"segnale={style.signal}; diretto={style.directness:.2f}; brevità={1-style.verbosity:.2f}; "
                f"calore={style.warmth:.2f}; umorismo={style.humor:.2f}; sarcasmo={style.sarcasm:.2f}; "
                f"formalità={style.formality:.2f}; empatia={style.empathy:.2f}; sicurezza espressiva={style.confidence_style:.2f}. "
                "Non modificare intenti, rischi, conferme, strumenti o azioni. "
                "Niente emoji, catchphrase o emozioni simulate.")
