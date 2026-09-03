from __future__ import annotations
import json
import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")
_SECRET = re.compile(r"(?i)(api[_-]?key|password|authorization|bearer|secret|token)(\s*[:=]\s*)([^\s,;\"']+)")


def redact(value):
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(
                    word in str(key).casefold() for word in ("password", "secret", "token", "api_key", "authorization")
                )
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(redact(parsed), ensure_ascii=False, default=str)
        return _SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "module": record.name,
            "event": redact(record.getMessage()),
        }
        row.update({k: redact(v) for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            row["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(row, ensure_ascii=False, default=str)


def configure_logging(
    path: Path, *, level: int = logging.INFO, max_bytes: int = 5_000_000, backup_count: int = 5
) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jarvis")
    logger.setLevel(level)
    logger.propagate = False
    with threading.Lock():
        if not any(getattr(handler, "baseFilename", None) == str(path.resolve()) for handler in logger.handlers):
            handler = RotatingFileHandler(
                path, maxBytes=max(1024, int(max_bytes)), backupCount=max(1, int(backup_count)), encoding="utf-8"
            )
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
    return logger
