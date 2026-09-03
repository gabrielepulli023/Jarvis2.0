from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class RiskLevel(StrEnum):
    SAFE = "safe"
    SENSITIVE = "sensitive"
    ADMIN = "admin"
    DESTRUCTIVE = "destructive"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    risk: RiskLevel
    category: str
    confirmation_required: bool


class RiskClassifier:
    """Deterministic policy metadata. Model output never controls action risk."""

    _POLICIES: Mapping[str, ActionPolicy] = {
        "chiudi_programma": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "chiudi_finestra": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "sposta": ActionPolicy(RiskLevel.SENSITIVE, "files_write", True),
        "rinomina": ActionPolicy(RiskLevel.SENSITIVE, "files_write", True),
        "imposta_clipboard": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "run_script": ActionPolicy(RiskLevel.SENSITIVE, "scripts", True),
        "test_project": ActionPolicy(RiskLevel.SENSITIVE, "scripts", True),
        # High-level external agents can perform several GUI/network actions
        # from one natural-language task, therefore every invocation requires
        # explicit confirmation even when the underlying task sounds harmless.
        "delegate_agent_task": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "browser_agent_task": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "ufo_agent_task": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "ui_tars_agent_task": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "mem0_remember": ActionPolicy(RiskLevel.SENSITIVE, "computer", True),
        "installa_programma": ActionPolicy(RiskLevel.ADMIN, "install", True),
        "aggiorna_programma": ActionPolicy(RiskLevel.ADMIN, "install", True),
        "termina_processo": ActionPolicy(RiskLevel.DESTRUCTIVE, "destructive", True),
        "elimina": ActionPolicy(RiskLevel.DESTRUCTIVE, "destructive", True),
        "spegni_pc": ActionPolicy(RiskLevel.DESTRUCTIVE, "destructive", True),
        "riavvia_pc": ActionPolicy(RiskLevel.DESTRUCTIVE, "destructive", True),
        "sospendi_pc": ActionPolicy(RiskLevel.DESTRUCTIVE, "destructive", True),
        "disable_permission_engine": ActionPolicy(RiskLevel.FORBIDDEN, "forbidden", True),
        "disable_security_controls": ActionPolicy(RiskLevel.FORBIDDEN, "forbidden", True),
    }

    def classify(self, tool_name: str) -> ActionPolicy:
        return self._POLICIES.get(str(tool_name), ActionPolicy(RiskLevel.SAFE, "computer", False))


class PermissionEngine:
    def evaluate(self, policy: ActionPolicy, category_decision: str, *, confirmed: bool = False) -> str:
        if policy.risk is RiskLevel.FORBIDDEN or category_decision == "deny":
            return "deny"
        if category_decision == "confirm" or policy.confirmation_required:
            return "allow" if confirmed else "confirm"
        return "allow"
