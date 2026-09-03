from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeMode:
    safe: bool = False

    @classmethod
    def detect(cls, argv: list[str] | None = None) -> "RuntimeMode":
        arguments = sys.argv[1:] if argv is None else argv
        environment = os.getenv("JARVIS_SAFE_MODE", "").strip().lower()
        return cls(safe="--safe" in arguments or environment in {"1", "true", "yes", "on"})

    def permits(self, capability: str) -> bool:
        if not self.safe:
            return True
        return str(capability) not in {
            "CONTROL_MOUSE",
            "CONTROL_KEYBOARD",
            "WRITE_FILES",
            "PROCESS_CONTROL",
            "BROWSER_CONTROL",
            "SYSTEM_SETTINGS",
        }


RUNTIME_MODE = RuntimeMode.detect()
