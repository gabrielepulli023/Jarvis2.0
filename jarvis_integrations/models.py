from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IntegrationResult:
    success: bool
    backend: str
    message: str = ""
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "successo": bool(self.success),
            "messaggio": str(self.message or ""),
            "dati": self.data if isinstance(self.data, (dict, list, str, int, float, bool, type(None))) else str(self.data),
            "backend": self.backend,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def ok(cls, backend: str, message: str = "", data: Any = None, **metadata: Any) -> "IntegrationResult":
        return cls(True, backend, message, data, metadata)

    @classmethod
    def fail(cls, backend: str, message: str, data: Any = None, **metadata: Any) -> "IntegrationResult":
        return cls(False, backend, message, data, metadata)
