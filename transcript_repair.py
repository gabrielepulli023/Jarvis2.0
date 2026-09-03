"""Context-aware repair of STT entities used by operational commands.

This module deliberately does not rewrite free text.  It resolves only the
entity selected by a known command intent (application or site), preserving
the raw transcript for diagnostics.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class RepairResult:
    raw_transcript: str
    normalized_transcript: str
    intent: str | None = None
    entity_type: str | None = None
    entity_raw: str | None = None
    canonical_entity: str | None = None
    confidence: float = 0.0
    confidence_band: str = "low"
    reason: str = "no contextual entity"
    clarification: tuple[str, ...] = ()


_INTENT_PATTERNS = (
    ("OPEN_APPLICATION", "application", re.compile(r"^(?:apri|aprimi|aprire|avvia|avviare|lancia|lanciare)\s+(.+)$", re.I)),
    ("CLOSE_APPLICATION", "application", re.compile(r"^(?:chiudi|termina)\s+(.+)$", re.I)),
    ("OPEN_SITE", "site", re.compile(r"^(?:vai|naviga)\s+(?:su|a)\s+(.+)$", re.I)),
)


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _plain(value))


def _phonetic_forms(value: str) -> set[str]:
    """Small, language-agnostic pronunciation approximation for brand names."""
    base = _key(value)
    if not base:
        return set()
    forms = {base}
    for form in tuple(forms):
        form = form.replace("ph", "f").replace("ck", "k").replace("qu", "k")
        form = form.replace("y", "ai")
        form = form.replace("c", "k")
        forms.add(form)
        forms.add(re.sub(r"e$", "", form))
        forms.add(re.sub(r"d$", "", form))
    # A common Italian pronunciation of YouTube is "iutub".
    if base == "youtube":
        forms.update({"iutub", "iutube"})
    return {item for item in forms if item}


def _similar(query: str, candidate: str) -> float:
    direct = SequenceMatcher(None, _key(query), _key(candidate)).ratio()
    phonetic = max(
        (SequenceMatcher(None, left, right).ratio() for left in _phonetic_forms(query) for right in _phonetic_forms(candidate)),
        default=0.0,
    )
    return max(direct, phonetic)


def _registry(domain: str, candidates=None) -> list[str]:
    if candidates is not None:
        return list(dict.fromkeys(str(item).strip() for item in candidates if str(item).strip()))
    try:
        from settings_store import get_setting
        configured = get_setting("application_aliases", {}) if domain == "application" else get_setting("site_aliases", {})
    except Exception:
        configured = {}
    values: list[str] = []
    try:
        from tools import APPS, SITI
        source = APPS if domain == "application" else SITI
        values.extend(source.keys())
    except (ImportError, AttributeError):
        pass
    if isinstance(configured, dict):
        values.extend(configured.keys())
        for canonical, aliases in configured.items():
            values.append(str(canonical))
            if isinstance(aliases, (list, tuple)):
                values.extend(str(alias) for alias in aliases)
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _canonical(name: str, domain: str) -> str:
    try:
        from settings_store import get_setting
        configured = get_setting("application_aliases", {}) if domain == "application" else get_setting("site_aliases", {})
        for canonical, aliases in configured.items() if isinstance(configured, dict) else ():
            if _plain(name) == _plain(canonical) or any(_plain(name) == _plain(alias) for alias in aliases if isinstance(aliases, (list, tuple))):
                return str(canonical)
    except Exception:
        pass
    known = {
        "chrome": "Chrome", "google chrome": "Google Chrome", "spotify": "Spotify",
        "discord": "Discord", "visual studio code": "Visual Studio Code", "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code", "youtube": "YouTube", "google": "Google",
        "github": "GitHub", "openai": "OpenAI", "chatgpt": "ChatGPT",
    }
    return known.get(_plain(name), name)


def resolve_entity(query: str, entity_type: str, candidates=None) -> tuple[str | None, float, tuple[str, ...], str]:
    options = _registry(entity_type, candidates)
    scored = sorted((( _similar(query, option), option) for option in options), reverse=True)
    if not scored or scored[0][0] < 0.72:
        return None, scored[0][0] if scored else 0.0, (), "no sufficiently similar registry entity"
    top_score, top = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if _key(query) == _key(top):
        return _canonical(top, entity_type), 1.0, (), "exact registry match"
    if top_score < 0.84:
        return None, top_score, (), "low-confidence contextual match"
    if len(scored) > 1 and top_score - second_score < 0.12:
        choices = tuple(_canonical(name, entity_type) for score, name in scored if top_score - score < 0.08)[:3]
        return None, top_score, choices, "ambiguous contextual match"
    return _canonical(top, entity_type), min(0.99, top_score), (), "application/site fuzzy phonetic match"


def repair_transcript(raw_transcript: str, candidates=None) -> RepairResult:
    raw = str(raw_transcript or "").strip()
    value = re.sub(r"^(?:jarvis[\\s,;:]+)?", "", raw, flags=re.I).strip()
    value = re.sub(r"[\\s.!?,;:]+$", "", value).strip()
    for intent, entity_type, pattern in _INTENT_PATTERNS:
        match = pattern.fullmatch(value)
        if not match:
            continue
        entity_raw = match.group(1).strip()
        # URLs, paths and filenames are data, not registry entities.
        if entity_type == "site" and re.search(r'(?:https?://|www\.|[\\/]|\")', entity_raw, re.I):
            break
        resolved, score, choices, reason = resolve_entity(entity_raw, entity_type, candidates)
        if choices:
            return RepairResult(raw, raw, intent, entity_type, entity_raw, None, score, "medium", reason, choices)
        if resolved:
            prefix = value[: match.start(1)]
            normalized = prefix + resolved
            return RepairResult(raw, normalized, intent, entity_type, entity_raw, resolved, score, "high", reason)
        return RepairResult(raw, raw, intent, entity_type, entity_raw, None, score, "low", reason)
    return RepairResult(raw, raw)


def stt_context_prompt() -> str:
    """Build a bounded prompt from the existing application/site registry."""
    names = _registry("application") + _registry("site")
    unique = list(dict.fromkeys(_canonical(name, "application" if name in _registry("application") else "site") for name in names))[:120]
    return "Italian command transcription. Preserve proper names and technology terms exactly when heard: " + ", ".join(unique)
