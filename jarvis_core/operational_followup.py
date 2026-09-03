"""Deterministic interpretation and execution of short operational follow-ups."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class FollowUpIntent:
    action: str
    destination: str | None = None
    filename: str | None = None
    application: str | None = None


_AFFIRMATIVE = re.compile(r"^(?:s[iì]|si grazie|s[iì] grazie|ok|okay|va bene|certo|procedi|vai|fallo|fai pure|continua)$", re.I)
_OPEN = re.compile(r"^(?:apri|aprilo|aprila|aprirlo|aprirla)(?:\s+(?:con|usando)\s+(.+?))?[.!?]*$", re.I)
_SAVE = re.compile(
    r"\b(?:salva(?:lo|la|li|le)?|esporta(?:lo|la|li|le)?|scrivi(?:lo|la|li|le)?|"
    r"metti(?:lo|la|li|le)?|crea(?:\s+il)?\s+file|archivia|fallo)\b",
    re.I,
)
_DESTINATION = re.compile(r"\b(?:su|sul|sulla|nel|nella|in|nei|nelle)\s+(desktop|scrivania|download|downloads)\b", re.I)
_EXPLICIT_PATH = re.compile(r"(?:\b(?:su|sul|sulla|nel|nella|in)\s+)?([A-Za-z]:[\\/][^,;]+)", re.I)
_PREVIOUS_RESULT_REFERENCE = re.compile(
    r"\b(?:quello|quella|quelli|quelle|risultato(?:\s+(?:precedente|di\s+prima|appena\s+creato))?|"
    r"markdown\s+(?:appena\s+creato|precedente)|documento\s+(?:appena\s+creato|precedente)|"
    r"file\s+(?:appena\s+creato|precedente)|di\s+prima|appena\s+(?:creato|generato|convertito))\b",
    re.I,
)
_PRONOMINAL_ACTION = re.compile(
    r"\b(?:salva|esporta|scrivi|metti|archivia|fallo)(?:lo|la|li|le)\b|\bmettil[oaie]\b|\bfallo\b",
    re.I,
)
_DIRECT_DATA_REFERENCE = re.compile(
    r"\b(?:segreto|secret|password|token|api\s*key|configurazione|testo)\b|"
    r"\b(?:keyring|credential\s+manager|gestore\s+credenziali)\b",
    re.I,
)


def _refers_to_previous_result(value: str) -> bool:
    """Return whether a save-like command names an earlier operational result."""
    # Explicit secret/configuration destinations are self-contained commands.
    # They must never be mistaken for a request to reuse the previous artifact.
    if _DIRECT_DATA_REFERENCE.search(value):
        return False
    if _PRONOMINAL_ACTION.search(value) or _PREVIOUS_RESULT_REFERENCE.search(value):
        return True
    # A bare destination has no payload of its own and therefore means "save
    # the result we were just discussing" when it reaches this detector.
    return bool(re.search(r"\b(?:salva|esporta|scrivi|metti|archivia)\b\s+"
                          r"(?:su|sul|sulla|nel|nella|in|nei|nelle)\s+"
                          r"(?:desktop|scrivania|download|downloads)\b", value, re.I))


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_filename(value: str | None) -> str | None:
    if not value:
        return None
    leaf = Path(value.replace("\\", "/")).name.strip().strip("\"'")
    if not leaf or leaf in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', leaf):
        return None
    return leaf


def _filename_from_text(text: str) -> str | None:
    match = re.search(r"\b(?:come|chiamalo|chiamala|con nome)\s+[\"']?([^\"']+?)[\"']?(?:\s+(?:su|sul|sulla|nel|nella|in|nei|nelle)\b|$)", text, re.I)
    return _clean_filename(match.group(1).strip() if match else None)


def classify(text: str, *, has_context: bool = False) -> FollowUpIntent | None:
    """Classify only terse commands that can safely be tied to a prior result."""
    value = _text(text).rstrip(".!?").strip()
    if not value:
        return None
    opening = _OPEN.fullmatch(value)
    if opening:
        application = _text(opening.group(1)) or None
        return FollowUpIntent("open", application=application)
    if _SAVE.search(value) and _refers_to_previous_result(value):
        destination = None
        location = _DESTINATION.search(value)
        if location:
            destination = location.group(1).casefold()
        elif re.search(r"\b(?:lì|li)\b", value, re.I):
            destination = "previous"
        explicit_path = _EXPLICIT_PATH.search(value)
        if explicit_path:
            destination = explicit_path.group(1).strip().strip("\"'")
        return FollowUpIntent("save", destination=destination, filename=_filename_from_text(value))
    if has_context and _AFFIRMATIVE.fullmatch(value):
        return FollowUpIntent("continue")
    return None


def is_operational_followup(text: str, context: Mapping[str, Any] | bool | None = None) -> bool:
    has_context = bool(context) if isinstance(context, Mapping) else context is True
    return classify(text, has_context=has_context) is not None


def _directory(destination: str | None, context: Mapping[str, Any]) -> Path:
    label = str(destination or "").casefold()
    if label in {"desktop", "scrivania"}:
        return Path.home() / "Desktop"
    if label in {"download", "downloads"}:
        return Path.home() / "Downloads"
    if label == "previous":
        source = str(context.get("source_path") or "").strip()
        if source:
            return Path(source).expanduser().resolve().parent
    if label:
        return Path(label).expanduser().resolve()
    source = str(context.get("source_path") or "").strip()
    if source:
        return Path(source).expanduser().resolve().parent
    return Path.home() / "Desktop"


def _target(context: Mapping[str, Any], intent: FollowUpIntent) -> Path:
    filename = _clean_filename(intent.filename or str(context.get("filename") or ""))
    if not filename:
        filename = "risultato.md" if context.get("content_key") == "markdown" else "risultato.txt"
    explicit = intent.destination or ""
    if explicit and re.match(r"^[A-Za-z]:[\\/]", explicit):
        explicit_path = Path(explicit).expanduser().resolve()
        # A path with a filename is accepted; a path ending in a separator is a directory.
        if explicit_path.suffix and not explicit.endswith(("\\", "/")):
            return explicit_path
        return explicit_path / filename
    return _directory(intent.destination, context) / filename


def _success(result: Mapping[str, Any] | None) -> bool:
    return bool((result or {}).get("successo", (result or {}).get("success", False)))


def _verified(result: Mapping[str, Any] | None, *, expected_content: str | None = None) -> bool:
    value = dict(result or {})
    if not _success(value):
        return False
    verification = value.get("verification")
    if isinstance(verification, Mapping) and verification.get("status") == "verified":
        return True
    data = value.get("dati") if isinstance(value.get("dati"), Mapping) else value.get("data")
    if isinstance(data, Mapping) and data.get("verified") is True:
        return True
    path = data.get("path") if isinstance(data, Mapping) else None
    if path and expected_content is not None:
        target = Path(str(path))
        try:
            return target.is_file() and target.read_text(encoding="utf-8") == expected_content
        except (OSError, UnicodeError):
            return False
    return False


def execute(
    text: str,
    context: Mapping[str, Any] | None,
    *,
    writer: Callable[[str, str], Mapping[str, Any]],
    opener: Callable[[str, str | None], Mapping[str, Any]],
) -> tuple[bool, str, dict[str, Any]] | None:
    """Execute a recognized follow-up, returning only verified confirmations."""
    intent = classify(text, has_context=bool(context))
    if intent is None:
        return None
    if not context or context.get("status") != "succeeded" or context.get("verification_status") != "verified":
        action = "aprire" if intent.action == "open" else "salvare"
        return True, f"Non posso {action}: non ho un risultato operativo recente e verificato da utilizzare. Indica cosa devo {action}.", {"successo": False, "stato": "missing_context"}
    if intent.action == "continue":
        return True, "Indica quale azione vuoi eseguire sul risultato operativo precedente.", {"successo": False, "stato": "needs_instruction"}
    if intent.action == "save":
        content = context.get("content")
        if not isinstance(content, str):
            return True, "Non posso salvare: il risultato precedente non contiene contenuto utilizzabile.", {"successo": False, "stato": "missing_content"}
        target = _target(context, intent)
        result = dict(writer(str(target), content) or {})
        if not _verified(result, expected_content=content):
            return True, str(result.get("messaggio") or result.get("message") or "Non ho salvato il risultato: la verifica del file non è riuscita."), result
        location = "Desktop" if target.parent.name.casefold() in {"desktop", "scrivania"} else target.parent.name
        return True, f"Ho salvato {target.name} in {location}.", result
    path = str(context.get("artifact_path") or context.get("source_path") or "").strip()
    if not path:
        return True, "Non posso aprire: il risultato precedente non contiene un percorso verificabile.", {"successo": False, "stato": "missing_path"}
    result = dict(opener(path, intent.application) or {})
    if not _verified(result):
        return True, str(result.get("messaggio") or result.get("message") or "Non ho aperto il percorso: la verifica non è riuscita."), result
    return True, f"Ho aperto {Path(path).name or path}.", result
