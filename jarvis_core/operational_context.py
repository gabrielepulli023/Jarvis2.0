"""Short-lived context for results that can drive a subsequent operation.

This is deliberately separate from conversational memory.  It is an in-memory,
bounded hand-off between the operational tool loop and the next user turn.  A
failed or expired result is never silently replaced by an older reusable one.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_TTL_SECONDS = 300.0
_CONTENT_KEYS = ("markdown", "content", "contenuto", "text", "testo", "body", "output")
_PATH_KEYS = ("path", "percorso", "source_path", "file_path", "output_path", "target")
_FILENAME_KEYS = ("filename", "file_name", "nome_file", "name", "nome")
_REDACTION_MARKER = "***REDACTED***"
_SENSITIVE_KEYS = {"secret", "password", "token", "api_key", "apikey", "authorization", "bearer"}
_INLINE_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|password|authorization|bearer|secret|token)(\s*[:=]\s*)([^\s,;\"']+)"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(("_secret", "_password", "_token", "_api_key"))


def _sensitive_values(value: Any) -> set[str]:
    """Collect scalar secret values so they can also be removed from messages."""
    if isinstance(value, Mapping):
        found: set[str] = set()
        for key, item in value.items():
            if _is_sensitive_key(key) and isinstance(item, (str, int, float)) and not isinstance(item, bool):
                candidate = str(item).strip()
                if candidate:
                    found.add(candidate)
            elif str(key).casefold() == "arguments_json" and isinstance(item, str):
                try:
                    parsed = json.loads(item)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None:
                    found.update(_sensitive_values(parsed))
            else:
                found.update(_sensitive_values(item))
        return found
    if isinstance(value, (list, tuple)):
        found: set[str] = set()
        for item in value:
            found.update(_sensitive_values(item))
        return found
    return set()


def _redact_sensitive(value: Any, sensitive_values: set[str] | None = None) -> Any:
    values = sensitive_values or set()
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[str(key)] = _REDACTION_MARKER
            elif str(key).casefold() == "arguments_json" and isinstance(item, str):
                try:
                    parsed = json.loads(item)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None:
                    redacted_parsed = _redact_sensitive(parsed, values)
                    redacted[str(key)] = (
                        item
                        if redacted_parsed == parsed
                        else json.dumps(redacted_parsed, ensure_ascii=False)
                    )
                else:
                    redacted[str(key)] = _redact_sensitive(item, values)
            else:
                redacted[str(key)] = _redact_sensitive(item, values)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item, values) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted(values, key=len, reverse=True):
            if secret and secret != _REDACTION_MARKER:
                redacted = redacted.replace(secret, _REDACTION_MARKER)
        return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}{_REDACTION_MARKER}", redacted)
    return value


def _first_text(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _find_content(value: Any, *, depth: int = 0) -> tuple[str | None, str | None]:
    if depth > 3:
        return None, None
    if isinstance(value, (list, tuple)):
        for nested in value[:20]:
            content, key = _find_content(nested, depth=depth + 1)
            if content is not None:
                return content, key
        return None, None
    data = _mapping(value)
    for key in _CONTENT_KEYS:
        candidate = data.get(key)
        if isinstance(candidate, str):
            return candidate, key
    for nested in data.values():
        if isinstance(nested, (Mapping, list, tuple)):
            content, key = _find_content(nested, depth=depth + 1)
            if content is not None:
                return content, key
    return None, None


def _find_path(value: Any, *, depth: int = 0) -> str | None:
    if depth > 3:
        return None
    data = _mapping(value)
    path = _first_text(data, _PATH_KEYS)
    if path:
        return path
    for nested in data.values():
        if isinstance(nested, Mapping):
            path = _find_path(nested, depth=depth + 1)
            if path:
                return path
    return None


def _clean_filename(value: str | None) -> str | None:
    if not value:
        return None
    # A tool may return a full path.  Only the leaf may become a new filename.
    leaf = Path(value.replace("\\", "/")).name.strip()
    if not leaf or leaf in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', leaf):
        return None
    return leaf


class OperationalContext:
    """Thread-safe, single-item, expiring operational result hand-off."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock=time.time):
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._clock = clock
        self._lock = threading.RLock()
        self._latest: dict[str, Any] | None = None

    def record(self, tool: str, result: Mapping[str, Any] | None, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Record the actual normalized result of one tool invocation.

        Only successful content/path fields are retained as reusable data.  The
        complete string returned by a conversion tool is kept; no truncation is
        applied here.  Failures and permission/confirmation responses replace
        the previous item so an old artifact cannot be reused accidentally.
        """
        raw_value = dict(result or {})
        raw_args = _mapping(arguments)
        sensitive_values = _sensitive_values(raw_args)
        value = _redact_sensitive(raw_value, sensitive_values)
        args = _redact_sensitive(raw_args, sensitive_values)
        data = _mapping(value.get("dati"))
        success = bool(value.get("successo"))
        pending = bool(value.get("richiede_conferma"))
        verification = _mapping(value.get("verification"))
        verification_status = str(verification.get("status") or "")
        if not success:
            status = "pending" if pending else "failed"
        elif verification_status != "verified":
            status = "unverified"
        else:
            status = "succeeded"

        content, content_key = _find_content(data)
        source_path = _find_path(data) or _first_text(args, ("path", "percorso", "source", "source_path"))
        filename = _clean_filename(_first_text(data, _FILENAME_KEYS) or _first_text(args, _FILENAME_KEYS))
        if not filename and source_path and content_key == "markdown":
            filename = f"{Path(source_path).stem}.md"
        elif not filename and source_path and content is not None:
            filename = f"{Path(source_path).stem}.txt"

        artifact_path = _first_text(data, ("output_path", "target", "path", "percorso"))
        skill = str(value.get("skill") or data.get("skill") or "").strip() or None
        now = float(self._clock())
        action_id = str(value.get("azione_id") or data.get("action_id") or "").strip() or None
        pending_action = None
        if pending and action_id:
            pending_action = {
                "action_id": action_id,
                "tool": str(tool or "").strip(),
                "skill": skill,
                "arguments": dict(args),
                "timestamp": now,
                "risk": str(value.get("rischio") or data.get("risk") or "").strip() or None,
                "state": "pending_confirmation",
            }
        row = {
            "tool": str(tool or "").strip(),
            "skill": skill,
            "action_id": action_id,
            "pending_action": pending_action,
            "source_path": source_path,
            "artifact_path": artifact_path,
            "content": content if success else None,
            "markdown": content if success and content_key == "markdown" else None,
            "content_key": content_key,
            "filename": filename,
            "timestamp": now,
            "timestamp_iso": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "status": status,
            "verification_status": verification_status or ("unverified" if success else "failed"),
            "truncated": bool(data.get("truncated")),
            "message": str(value.get("messaggio") or "")[:1000],
        }
        with self._lock:
            self._latest = row
        return dict(row)

    def current(self, *, max_age: float | None = None) -> dict[str, Any] | None:
        with self._lock:
            row = self._latest
            if row is None:
                return None
            age_limit = self.ttl_seconds if max_age is None else max(0.0, float(max_age))
            if float(self._clock()) - float(row["timestamp"]) > age_limit:
                self._latest = None
                return None
            return dict(row)

    def clear(self) -> None:
        with self._lock:
            self._latest = None
