"""Manifest-backed routing helpers for the isolated Expansion skills."""
from __future__ import annotations

import re
from typing import Any

from jarvis_skills import SkillRegistry


_ENTRYPOINT_PREFIX = "jarvis_expansion:"
_QDRANT_ADD_PREFIX = re.compile(
    r"^\s*(?:aggiungi|salva|memorizza|inserisci|conserva)\s+"
    r"(?:(?:questo|questa|il\s+seguente|la\s+seguente)\s+)?"
    r"(?:(?:alla|nella|in)\s+)?memoria\s+vettoriale"
    r"(?:\s+(?:con|in|su|tramite|usando)\s+qdrant)?\s*[:,-]?\s*",
    re.IGNORECASE,
)
_QDRANT_SEARCH_PREFIX = re.compile(
    r"^\s*(?:cerca|ricerca|trova|recupera)\s+"
    r"(?:(?:con|in|nella|dalla|su)\s+)?"
    r"memoria\s+vettoriale(?:\s+qdrant)?\s*[:,-]?\s*",
    re.IGNORECASE,
)
_QDRANT_ACTION_WORDS = re.compile(
    r"\b(?:aggiungi|salva|memorizza|memorizzare|inserisci|conserva|conservare)\b",
    re.IGNORECASE,
)
_QDRANT_SEARCH_WORDS = re.compile(
    r"\b(?:cerca|ricerca|trova|recupera|recuperare)\b",
    re.IGNORECASE,
)
_SECRET_STORE_ACTION = re.compile(
    r"\b(?:salva|memorizza|conserva|archivia|registra)\b",
    re.IGNORECASE,
)
_SECRET_DELETE_ACTION = re.compile(r"\b(?:elimina|cancella|rimuovi)\b", re.IGNORECASE)
_SECRET_STORE_TARGET = re.compile(
    r"\b(?:keyring|credential\s+manager|gestore\s+credenziali)\b",
    re.IGNORECASE,
)
_SECRET_DELETE_TARGET = re.compile(
    r"\b(?:keyring|credential\s+manager|gestore\s+credenziali|credenziale|segreto|password|token|api\s*key)\b",
    re.IGNORECASE,
)
_SECRET_KIND = r"(?:segreto|secret|password|token|api\s*key)"
_SECRET_KIND_WORDS = re.compile(rf"\b{_SECRET_KIND}\b", re.IGNORECASE)
_SECRET_FIELD_LABELS = r"(?:servizio|service|username|user\s*name|nome\s+utente|utente)"
_SECRET_TARGET_LABELS = r"(?:keyring|credential\s+manager|gestore\s+credenziali)"
_SECRET_STOP_LABELS = rf"(?:{_SECRET_FIELD_LABELS}|{_SECRET_KIND}|{_SECRET_TARGET_LABELS})"
_LITELLM_MODEL = re.compile(
    r"\b(?:modello|model)\b\s*(?::|=|è|e')?\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9._:/-]+))",
    re.IGNORECASE,
)
_LITELLM_PROMPT = re.compile(
    r"\b(?:prompt|testo|messaggio)\b\s*(?::|=)?\s*(?:\"([^\"]+)\"|'([^']+)'|(.+?))\s*$",
    re.IGNORECASE,
)
_LITELLM_EXACT = re.compile(
    r"rispondi\s+esattamente\s+con\s*(?::|=)?\s*[\"']?(.+?)[\"']?\s*[.!?]*$",
    re.IGNORECASE,
)


def _extract_labeled_value(text: str, labels: str, stop_labels: str) -> str | None:
    """Extract a quoted or plain value up to the next known field label."""
    match = re.search(
        rf"\b(?:{labels})\b\s*(?::|=)?\s*(?P<quoted>\"[^\"]*\"|'[^']*'|"
        rf"(?P<plain>.+?))(?=\s+(?:(?:con|e|per|nel|nella|nei|nelle|in|su|sul|sulla)\s+)?(?:{stop_labels})\b|[.!?]\s*$|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group("quoted") if match.group("quoted") is not None else match.group("plain")
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value or None


def secrets_arguments(skill: str, text: str) -> dict[str, str] | None:
    """Extract complete Keyring arguments without ever extracting a secret value for delete."""
    if skill not in {"secrets.store", "secrets.delete"}:
        return None
    value = str(text or "").strip()
    if skill == "secrets.store" and (not _SECRET_STORE_ACTION.search(value) or not _SECRET_KIND_WORDS.search(value)):
        return None
    if skill == "secrets.delete" and (
        not _SECRET_DELETE_ACTION.search(value) or not _SECRET_DELETE_TARGET.search(value)
    ):
        return None

    service = _extract_labeled_value(value, _SECRET_FIELD_LABELS, _SECRET_STOP_LABELS)
    username = _extract_labeled_value(value, r"username|user\s*name|nome\s+utente|utente", _SECRET_STOP_LABELS)
    secret = _extract_labeled_value(value, _SECRET_KIND, _SECRET_STOP_LABELS) if skill == "secrets.store" else None
    if secret:
        secret = re.sub(r"\s+(?:nel|nella|nei|nelle|in|su|sul|sulla)\s*$", "", secret, flags=re.IGNORECASE).strip()
        if secret.casefold() in {"nel", "nella", "nei", "nelle", "in", "su", "sul", "sulla"}:
            secret = None
    if not service or not username or (skill == "secrets.store" and not secret):
        return None

    # A Keyring/credential-manager marker is the strongest signal.  A complete
    # service + username form is also unambiguous for the registered store
    # skill, which covers equivalent wording such as "API key ... per service".
    if not _SECRET_STORE_TARGET.search(value) and not re.search(rf"\b(?:{_SECRET_FIELD_LABELS})\b", value, re.I):
        return None
    arguments = {"service": service, "username": username}
    if skill == "secrets.store":
        arguments["secret"] = secret
    return arguments


def litellm_arguments(text: str) -> dict[str, Any] | None:
    """Extract a complete LiteLLM request for the deterministic Expansion path."""
    value = str(text or "").strip()
    if "litellm" not in value.casefold():
        return None
    model_match = _LITELLM_MODEL.search(value)
    model = next((group.strip() for group in model_match.groups() if group and group.strip()), None) if model_match else None
    prompt_match = _LITELLM_PROMPT.search(value)
    prompt = next((group.strip() for group in prompt_match.groups() if group and group.strip()), None) if prompt_match else None
    if prompt is None:
        exact_match = _LITELLM_EXACT.search(value)
        if exact_match:
            prompt = f"Respond exactly with: {exact_match.group(1).strip().strip(chr(34) + chr(39))}"
    if not model or not prompt:
        return None
    arguments: dict[str, Any] = {"model": model, "prompt": prompt}
    tokens = re.search(r"\b(?:max[_ ]?tokens|token)\s*(?::|=)?\s*(\d+)\b", value, re.IGNORECASE)
    if tokens:
        arguments["max_tokens"] = int(tokens.group(1))
    return arguments


def expansion_skill_names(registry: SkillRegistry) -> set[str]:
    """Return the currently registered Expansion skills, without a duplicate whitelist."""
    return {
        row["name"]
        for row in registry.list()
        if str(row.get("entrypoint") or "").startswith(_ENTRYPOINT_PREFIX)
    }


def match_expansion_skill(registry: SkillRegistry, text: str) -> dict[str, Any] | None:
    """Resolve a user request through the registered Expansion manifest intents."""
    match = registry.best_intent_match(text, expansion_skill_names(registry))
    if match is not None:
        return match
    if "secrets.delete" in expansion_skill_names(registry):
        value = str(text or "")
        if _SECRET_DELETE_ACTION.search(value) and _SECRET_DELETE_TARGET.search(value):
            return {
                "skill": "secrets.delete",
                "intent": "semantic secret delete",
                "normalized_intent": "semantic secret delete",
                "token_count": 3,
                "character_count": 22,
                "entrypoint": "jarvis_expansion:keyring_delete",
            }
    return None


def _payload_after_qdrant(value: str) -> str:
    match = re.search(r"\bqdrant\b", value, re.IGNORECASE)
    if not match:
        return ""
    payload = value[match.end() :].strip()
    payload = re.sub(
        r"^(?:per\s+)?(?:memorizzare|memorizza|salvare|salva|aggiungere|aggiungi|"
        r"conservare|conserva|cercare|cerca|ricercare|ricerca)\b\s*[:,-]?\s*",
        "",
        payload,
        flags=re.IGNORECASE,
    )
    return payload.strip()


def _payload_after_colon(value: str) -> str:
    prefix, separator, payload = value.partition(":")
    if separator and (re.search(r"\bqdrant\b", prefix, re.IGNORECASE) or "memoria vettoriale" in prefix.casefold()):
        return payload.strip()
    return ""


def qdrant_arguments(skill: str, text: str) -> dict[str, Any] | None:
    """Extract only the payload needed by the deterministic Qdrant fast path."""
    value = str(text or "").strip()
    if skill == "qdrant.add":
        if not _QDRANT_ACTION_WORDS.search(value):
            return None
        payload = _payload_after_colon(value) or _payload_after_qdrant(value)
        if not payload:
            payload = _QDRANT_ADD_PREFIX.sub("", value, count=1).strip()
        return {"text": payload} if payload else None
    if skill == "qdrant.search":
        if not _QDRANT_SEARCH_WORDS.search(value):
            return None
        payload = _payload_after_colon(value) or _payload_after_qdrant(value)
        if not payload:
            payload = _QDRANT_SEARCH_PREFIX.sub("", value, count=1).strip()
        return {"query": payload} if payload else None
    return None
