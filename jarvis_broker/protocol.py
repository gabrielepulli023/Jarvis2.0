from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from permission_engine import RiskLevel


@dataclass(frozen=True, slots=True)
class BrokerRequest:
    request_id: str
    timestamp: float
    caller: str
    action: str
    parameters: dict[str, Any]
    risk_level: str
    user_confirmation: bool
    token: str


@dataclass(frozen=True, slots=True)
class BrokerResponse:
    request_id: str
    success: bool
    message: str
    data: dict[str, Any]


class BrokerProtocol:
    MAX_CLOCK_SKEW = 30.0
    ACTION_RISKS = {
        "broker.ping": RiskLevel.SAFE,
        "broker.stop": RiskLevel.SENSITIVE,
        "system.info": RiskLevel.SAFE,
        "software.list": RiskLevel.SAFE,
        "winget.list": RiskLevel.SAFE,
        "winget.search": RiskLevel.SAFE,
        "winget.install": RiskLevel.ADMIN,
        "winget.upgrade": RiskLevel.ADMIN,
        "winget.upgrade_all": RiskLevel.ADMIN,
        "winget.uninstall": RiskLevel.ADMIN,
        "service.list": RiskLevel.SAFE,
        "service.start": RiskLevel.ADMIN,
        "service.stop": RiskLevel.ADMIN,
        "firewall.list": RiskLevel.SAFE,
        "firewall.profile": RiskLevel.ADMIN,
        "firewall.rule_add": RiskLevel.ADMIN,
        "firewall.rule_remove": RiskLevel.ADMIN,
        "task.list": RiskLevel.SAFE,
        "task.enable": RiskLevel.ADMIN,
        "task.disable": RiskLevel.ADMIN,
        "driver.list": RiskLevel.SAFE,
        "driver.scan": RiskLevel.ADMIN,
        "windows_update.history": RiskLevel.SAFE,
        "windows_update.scan": RiskLevel.ADMIN,
        "startup.status": RiskLevel.SAFE,
        "startup.enable": RiskLevel.ADMIN,
        "startup.disable": RiskLevel.ADMIN,
        "power.lock": RiskLevel.SENSITIVE,
        "power.logout": RiskLevel.DESTRUCTIVE,
        "power.shutdown": RiskLevel.DESTRUCTIVE,
        "power.restart": RiskLevel.DESTRUCTIVE,
    }

    @staticmethod
    def _canonical(values: dict[str, Any]) -> bytes:
        unsigned = {key: value for key, value in values.items() if key != "token"}
        return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def create(
        cls,
        secret: bytes,
        caller: str,
        action: str,
        parameters: dict[str, Any],
        *,
        user_confirmation: bool = False,
        now: float | None = None,
    ) -> BrokerRequest:
        risk = cls.ACTION_RISKS.get(action)
        if risk is None:
            raise ValueError("Azione broker non registrata")
        values = {
            "request_id": str(uuid.uuid4()),
            "timestamp": float(now if now is not None else time.time()),
            "caller": str(caller),
            "action": action,
            "parameters": dict(parameters),
            "risk_level": risk.value,
            "user_confirmation": bool(user_confirmation),
        }
        values["token"] = hmac.new(secret, cls._canonical(values), hashlib.sha256).hexdigest()
        return BrokerRequest(**values)

    @classmethod
    def validate(
        cls, request: BrokerRequest, secret: bytes, *, expected_caller: str, seen: set[str], now: float | None = None
    ) -> None:
        current = float(now if now is not None else time.time())
        try:
            uuid.UUID(request.request_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("request_id non valido") from exc
        if request.request_id in seen:
            raise ValueError("richiesta duplicata")
        if abs(current - float(request.timestamp)) > cls.MAX_CLOCK_SKEW:
            raise ValueError("richiesta scaduta")
        if not hmac.compare_digest(request.caller, expected_caller):
            raise ValueError("caller non autorizzato")
        expected_risk = cls.ACTION_RISKS.get(request.action)
        if expected_risk is None or request.risk_level != expected_risk.value:
            raise ValueError("azione o rischio non valido")
        if (
            expected_risk in {RiskLevel.SENSITIVE, RiskLevel.ADMIN, RiskLevel.DESTRUCTIVE}
            and not request.user_confirmation
        ):
            raise PermissionError("conferma utente richiesta")
        expected = hmac.new(secret, cls._canonical(asdict(request)), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.token):
            raise PermissionError("firma richiesta non valida")
        seen.add(request.request_id)
