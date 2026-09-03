from __future__ import annotations

import re


_BLOCKED_PATTERNS = (
    r"\bpassword\b",
    r"\bpasscode\b",
    r"\botp\b",
    r"\b2fa\b",
    r"\bcodice\s+(?:di\s+)?verifica\b",
    r"\bcodice\s+sms\b",
    r"\bpag(?:a|are|amento|amenti)\b",
    r"\bacquist(?:a|are|o)\b",
    r"\bcompra(?:re)?\b",
    r"\binvia\s+(?:un\s+)?bonifico\b",
    r"\b(?:esegui|piazza|apri|chiudi)\s+(?:un\s+)?ordine\s+(?:finanziario|di\s+trading|di\s+borsa)\b",
)

_SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9_-]{16,}",
    r"(?i)api[_ -]?key\s*[:=]\s*\S+",
    r"(?i)password\s*[:=]\s*\S+",
    r"(?i)token\s*[:=]\s*\S+",
)


def guard_external_task(task: str) -> tuple[bool, str]:
    text = " ".join(str(task or "").split())
    if not text:
        return False, "Task vuoto."
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return False, "Task bloccato: gli agenti esterni non possono gestire credenziali, OTP, pagamenti, acquisti o ordini finanziari."
    return True, ""


def contains_secret(text: str) -> bool:
    value = str(text or "")
    return any(re.search(pattern, value) for pattern in _SECRET_PATTERNS)
