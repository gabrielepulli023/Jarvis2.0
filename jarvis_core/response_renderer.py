"""Central conversion from verified technical outcomes to user-facing replies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"(?<![\w:])[A-Za-z]:[\\/][^<>\r\n\"']+")
_UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:Users|home|tmp|var|opt|workspace)/[^\s<>\"']+")
_TECHNICAL_NAMES = {
    "searxng.search": "la ricerca sul web",
    "openhands.run": "il controllo e la correzione del codice",
    "ruff.check": "il controllo del codice",
    "qdrant.search": "la ricerca nei ricordi pertinenti",
    "qdrant.add": "il salvataggio nella memoria",
    "screenpipe.search": "la ricerca nella cronologia dello schermo",
    "expansion_call": "lo strumento necessario",
    "langgraph": "il flusso di lavoro",
    "mcp.call": "il servizio collegato",
}
_DETAIL_REQUEST_RE = re.compile(
    r"\b(?:url\s+completo|percorso\s+completo|dove\s+esattamente|errore\s+tecnico|"
    r"mostra\s+(?:i\s+)?dettagli|modalit(?:à|a)\s+tecnica)\b",
    re.IGNORECASE,
)
_LINK_REQUEST_RE = re.compile(r"\b(?:mandami|dammi|inviami|mostrami)\s+il\s+link\b", re.IGNORECASE)
_FAILURE_RE = re.compile(
    r"\b(?:non\s+(?:ho|sono|posso|riesco|trovo|trovato|disponibile)|errore|fallit|"
    r"permessi\s+negati|non\s+complet|non\s+verificat|richiede\s+ancora|"
    r"nessun\s+risultat|nessuna\s+risposta|bloccata)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TechnicalResult:
    success: bool
    message: str = ""
    verification_status: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    tool: str = ""
    skill: str = ""
    error: str = ""
    objective: str = ""
    complexity: str = "simple"
    technical_details: dict[str, Any] = field(default_factory=dict)

    @property
    def verified(self) -> bool | None:
        if self.verification_status:
            return self.verification_status == "verified"
        if self.success and self.data.get("verified") is True:
            return True
        return None


@dataclass(frozen=True)
class ConversationResult:
    spoken_response: str
    display_response: str
    verified: bool | None = None
    technical_mode: bool = False
    links: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


class ResponseRenderer:
    """Render one result twice, keeping speech concise and HUD details intact."""

    def render(
        self,
        result: TechnicalResult | dict[str, Any] | str,
        *,
        request: str = "",
        technical_mode: bool = False,
    ) -> ConversationResult:
        value = self._coerce(result)
        raw = str(value.message or "").strip()
        links = tuple(self._collect_urls(raw, value.data))
        detail_mode = bool(technical_mode or _DETAIL_REQUEST_RE.search(str(request or "")))
        display = raw or ("Operazione completata." if value.success else "Operazione non riuscita.")
        if links and not any(url in display for url in links):
            display += "\n\nLink:\n" + "\n".join(f"- {url}" for url in links)
        if detail_mode and value.technical_details:
            details = "; ".join(f"{key}: {item}" for key, item in value.technical_details.items())
            if details:
                display += f"\n\nDettagli tecnici: {details}"

        if detail_mode:
            spoken = self._clean(value.error or raw or display)
        elif not value.success:
            spoken = self._natural_error(value.error or raw)
        elif value.verification_status in {"failed", "unverified", "needs_verification"}:
            spoken = "Ho provato, ma non riesco ancora a verificare che sia riuscito."
        else:
            spoken = self._natural_success(raw or "Fatto.")

        if not detail_mode:
            spoken = self._hide_urls(spoken, links)
            spoken = self._hide_paths(spoken, request)
            spoken = self._hide_tool_names(spoken)
            if _LINK_REQUEST_RE.search(str(request or "")) and links:
                spoken = spoken.rstrip(" .") + ". Te l'ho messo a schermo."
        spoken = self._compact(spoken)
        if not spoken:
            spoken = "Fatto." if value.success else "Non sono riuscito a completare l'operazione."
        return ConversationResult(
            spoken_response=spoken,
            display_response=display,
            verified=value.verified,
            technical_mode=detail_mode,
            links=links,
            details=dict(value.technical_details),
        )

    @staticmethod
    def _coerce(result: TechnicalResult | dict[str, Any] | str) -> TechnicalResult:
        if isinstance(result, TechnicalResult):
            return result
        if isinstance(result, str):
            return TechnicalResult(True, result)
        value = dict(result or {})
        verification = value.get("verification")
        status = verification.get("status") if isinstance(verification, dict) else value.get("verification_status")
        data = value.get("data", value.get("dati", {}))
        return TechnicalResult(
            success=bool(value.get("success", value.get("successo", False))),
            message=str(value.get("message", value.get("messaggio", "")) or ""),
            verification_status=str(status) if status else None,
            data=dict(data) if isinstance(data, dict) else {},
            tool=str(value.get("tool", "") or ""),
            skill=str(value.get("skill", "") or ""),
            error=str(value.get("error", value.get("errore", "")) or ""),
            objective=str(value.get("objective", "") or ""),
            complexity=str(value.get("complexity", "simple") or "simple"),
            technical_details=dict(value.get("technical_details", {}))
            if isinstance(value.get("technical_details", {}), dict)
            else {},
        )

    @staticmethod
    def _collect_urls(message: str, data: dict[str, Any]) -> list[str]:
        found = list(_URL_RE.findall(message))

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).casefold() in {"url", "uri", "link", "href"} and isinstance(item, str):
                        found.extend(_URL_RE.findall(item))
                    elif str(key).casefold() in {"urls", "links"} and isinstance(item, (list, tuple)):
                        for entry in item:
                            if isinstance(entry, str):
                                found.extend(_URL_RE.findall(entry))
                    elif isinstance(item, (dict, list, tuple)):
                        visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)

        visit(data)
        return list(dict.fromkeys(url.rstrip(".,;:!?" ) for url in found))

    @staticmethod
    def _natural_error(value: str) -> str:
        lower = str(value or "").casefold()
        if "conferma" in lower or "pending_confirmation" in lower:
            return "Serve la tua conferma prima di procedere."
        if "permess" in lower or "policy" in lower or "bloccata" in lower:
            return "Non posso farlo con i permessi attuali."
        if any(token in lower for token in ("connectionerror", "timeout", "http 4", "http 5", "non raggiungibile", "connection refused")):
            return "Quel servizio al momento non risponde."
        if "non registrata" in lower or "entrypoint non collegato" in lower:
            return "Non trovo una capacità disponibile per questa richiesta."
        cleaned = ResponseRenderer._hide_tool_names(ResponseRenderer._hide_paths(value, ""))
        cleaned = ResponseRenderer._hide_urls(cleaned, _URL_RE.findall(cleaned))
        if not cleaned or "traceback" in lower or "stack trace" in lower:
            return "Non sono riuscito a completare l'operazione."
        return "Non sono riuscito a completare l'operazione. " + ResponseRenderer._compact(cleaned)

    @staticmethod
    def _hide_urls(text: str, urls: list[str] | tuple[str, ...]) -> str:
        result = str(text or "")
        for url in urls:
            host = (urlparse(url).hostname or "").removeprefix("www.")
            label = "il link"
            if "github.com" in host:
                label = "il repository su GitHub"
            elif "youtube.com" in host or "youtu.be" in host:
                label = "il video su YouTube"
            elif host:
                label = f"il risultato su {host}"
            result = result.replace(url, label)
        return result

    @staticmethod
    def _hide_paths(text: str, request: str) -> str:
        if _DETAIL_REQUEST_RE.search(str(request or "")) and re.search(r"(?:percorso|dove|path)", str(request), re.I):
            return str(text or "")

        def replace(match):
            path = match.group(0).rstrip(".,;:!?)]}")
            parts = re.split(r"[\\/]", path)
            filename = parts[-1] if parts else ""
            parent = parts[-2] if len(parts) > 1 else ""
            if parent and parent.casefold() not in {"users", "gabri", "desktop", "documents", "downloads"}:
                return f"nella cartella {parent}"
            if filename:
                return f"il file {filename}"
            return "il percorso indicato"

        result = _WINDOWS_PATH_RE.sub(replace, str(text or ""))
        return _UNIX_PATH_RE.sub(replace, result)

    @staticmethod
    def _hide_tool_names(text: str) -> str:
        result = str(text or "")
        for name, phrase in sorted(_TECHNICAL_NAMES.items(), key=lambda pair: -len(pair[0])):
            result = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", phrase, result, flags=re.I)
        result = re.sub(r"\b(?:tool|skill)\s+[a-z][\w-]*(?:\.[a-z][\w-]+)*\b", "lo strumento usato", result, flags=re.I)
        result = re.sub(r"\bho usato la ricerca sul web\b", "ho cercato sul web", result, flags=re.I)
        result = re.sub(r"\bho usato il controllo e la correzione del codice\b", "ho controllato e corretto il codice", result, flags=re.I)
        return result

    @staticmethod
    def _clean(text: str) -> str:
        value = str(text or "").replace("**", "").replace("`", "")
        value = re.sub(r"(?m)^\s*[-•]\s*", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @staticmethod
    def _natural_success(text: str) -> str:
        value = ResponseRenderer._clean(text)
        normalized = value.casefold().rstrip(".!?").strip()
        if normalized in {"operazione completata", "comando eseguito", "risultato ottenuto", "skill espansione completata"}:
            variants = ("Fatto.", "Ci sono.", "L'ho fatto.")
            return variants[sum(ord(char) for char in normalized) % len(variants)]
        return value

    @staticmethod
    def _compact(text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        return value if len(value) <= 700 else value[:697].rstrip() + "..."


RESPONSE_RENDERER = ResponseRenderer()


def message_indicates_failure(message: str) -> bool:
    """Infer a failure only for legacy tuple-based operational responses."""
    return bool(_FAILURE_RE.search(str(message or "")))


__all__ = [
    "ConversationResult",
    "RESPONSE_RENDERER",
    "ResponseRenderer",
    "TechnicalResult",
    "message_indicates_failure",
]
