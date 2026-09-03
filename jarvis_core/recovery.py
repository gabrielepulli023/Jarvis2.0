from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable

from .events import EventBus
from .logging import redact


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    max_retries: int = 2
    action_timeout: float = 15.0
    global_timeout: float = 60.0

    def __post_init__(self):
        if not 0 <= self.max_retries <= 10:
            raise ValueError("max_retries fuori limite")
        if not 0.01 <= self.action_timeout <= self.global_timeout:
            raise ValueError("timeout non validi")


@dataclass(frozen=True, slots=True)
class RecoveryStrategy:
    name: str
    execute: Callable[[], dict]
    verify: Callable[[dict, dict], bool]


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    strategy: str
    attempt: int
    success: bool
    verified: bool
    duration_ms: int
    error: str | None
    before: dict
    after: dict


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    success: bool
    final_status: str
    strategy: str | None
    attempts: tuple[RecoveryAttempt, ...]


class RecoveryEngine:
    """Bounded execute-observe-verify-recover loop with cancellation."""

    def __init__(self, events: EventBus, policy: RecoveryPolicy | None = None):
        self.events = events
        self.policy = policy or RecoveryPolicy()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-recovery")

    def run(
        self,
        action: str,
        strategies: list[RecoveryStrategy],
        capture_state: Callable[[], dict],
        *,
        cancellation: threading.Event | None = None,
    ) -> RecoveryResult:
        if not strategies:
            raise ValueError("Almeno una strategia è richiesta")
        cancellation = cancellation or threading.Event()
        started_global = time.monotonic()
        attempts: list[RecoveryAttempt] = []
        self.events.publish("recovery.started", {"action": action}, source="recovery")
        for strategy in strategies:
            for number in range(1, self.policy.max_retries + 2):
                if cancellation.is_set():
                    return self._finish(action, False, "cancelled", None, attempts)
                remaining = self.policy.global_timeout - (time.monotonic() - started_global)
                if remaining <= 0:
                    return self._finish(action, False, "global_timeout", None, attempts)
                before = dict(capture_state() or {})
                began = time.monotonic()
                error = None
                result = {}
                verified = False
                future = self._pool.submit(strategy.execute)
                try:
                    result = dict(future.result(timeout=min(self.policy.action_timeout, remaining)) or {})
                    after = dict(capture_state() or {})
                    executed = bool(result.get("success", result.get("successo", False)))
                    verified = executed and bool(strategy.verify(after, result))
                except FutureTimeout:
                    future.cancel()
                    after = dict(capture_state() or {})
                    error = "action_timeout"
                except Exception as exc:
                    after = dict(capture_state() or {})
                    error = redact(f"{type(exc).__name__}: {exc}")
                attempts.append(
                    RecoveryAttempt(
                        strategy.name,
                        number,
                        error is None,
                        verified,
                        int((time.monotonic() - began) * 1000),
                        error,
                        before,
                        after,
                    )
                )
                self.events.publish(
                    "recovery.attempt",
                    {
                        "action": action,
                        "strategy": strategy.name,
                        "attempt": number,
                        "verified": verified,
                        "error": error,
                    },
                    source="recovery",
                )
                if verified:
                    return self._finish(action, True, "success", strategy.name, attempts)
        return self._finish(action, False, "exhausted", None, attempts)

    def _finish(self, action, success, status, strategy, attempts):
        self.events.publish(
            "recovery.completed" if success else "recovery.failed",
            {"action": action, "status": status, "attempts": len(attempts)},
            source="recovery",
        )
        return RecoveryResult(success, status, strategy, tuple(attempts))

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
