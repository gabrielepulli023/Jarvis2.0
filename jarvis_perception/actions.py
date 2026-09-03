from __future__ import annotations
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable
from .state import PerceptionEngine, ScreenDiff, ScreenState
from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class ActionAttempt:
    strategy: str
    executed: bool
    verified: bool
    message: str
    result: dict


@dataclass(frozen=True, slots=True)
class VerifiedActionResult:
    success: bool
    strategy: str | None
    attempts: tuple[ActionAttempt, ...]
    observation: ScreenState | None
    diff: ScreenDiff | None


class VerifiedActionRunner:
    def __init__(self, perception: PerceptionEngine, anti_loop_limit: int = 2):
        self.perception = perception
        self.anti_loop_limit = max(1, anti_loop_limit)
        self._signatures: dict[str, int] = {}

    def run(
        self,
        action: str,
        arguments: dict,
        strategies: list[tuple[str, Callable[[], dict]]],
        expected: Callable[[ScreenState, ScreenDiff, dict], bool] | None = None,
        verification_timeout: float = 2,
    ) -> VerifiedActionResult:
        signature = hashlib.sha256(f"{action}|{json.dumps(arguments,sort_keys=True,default=str)}".encode()).hexdigest()
        self._signatures[signature] = self._signatures.get(signature, 0) + 1
        if self._signatures[signature] > self.anti_loop_limit:
            return VerifiedActionResult(
                False,
                None,
                (ActionAttempt("anti_loop", False, False, "Azione identica ripetuta senza progresso.", {}),),
                None,
                None,
            )
        attempts = []
        try:
            self.perception.observe()
        except RuntimeError:
            pass
        for name, strategy in strategies:
            try:
                result = dict(strategy() or {})
            except Exception as exc:
                attempts.append(ActionAttempt(name, False, False, redact(f"{type(exc).__name__}: {exc}"), {}))
                continue
            if not result.get("successo", result.get("success", False)):
                attempts.append(
                    ActionAttempt(name, True, False, str(result.get("messaggio", "execution failed")), result)
                )
                continue
            deadline = time.monotonic() + max(0.05, float(verification_timeout))
            state = None
            diff = None
            verified = False
            while time.monotonic() < deadline:
                try:
                    state = self.perception.observe()
                    diff = self.perception.diff()
                    verified = expected(state, diff, result) if expected else diff.has_progress
                except RuntimeError:
                    verified = False
                if verified:
                    break
                threading.Event().wait(0.05)
            attempts.append(
                ActionAttempt(
                    name, True, verified, "verified" if verified else "post-action condition not reached", result
                )
            )
            if verified:
                self._signatures.pop(signature, None)
                return VerifiedActionResult(True, name, tuple(attempts), state, diff)
        return VerifiedActionResult(False, None, tuple(attempts), None, None)

    def reset_progress(self) -> None:
        self._signatures.clear()
