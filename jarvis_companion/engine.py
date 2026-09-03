from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from jarvis_core.events import Event, EventBus
from jarvis_voice import SpeechPriority, VoiceState


class CompanionMode(StrEnum):
    PASSIVE = "passive"
    NORMAL = "normal"
    COMPANION = "companion"
    FOCUS = "focus"
    TRADING_COPILOT = "trading_copilot"
    CODING_COPILOT = "coding_copilot"
    DO_NOT_DISTURB = "do_not_disturb"


class Decision(StrEnum):
    SILENCE = "silence"
    HUD_ONLY = "hud_only"
    SPEAK = "speak"
    SPEAK_HIGH_PRIORITY = "speak_high_priority"


@dataclass(frozen=True, slots=True)
class InterventionCandidate:
    reason: str
    source: str
    category: str
    message: str
    importance: float
    confidence: float
    relevance: float = 1.0
    novelty: float = 1.0
    social_value: float = 0.0
    urgency: float = 0.0
    interruption_cost: float = 0.25
    critical: bool = False
    fingerprint: str = ""


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "mode": "normal",
    "coding_enabled": False,
    "trading_enabled": False,
    "speak_threshold": 0.80,
    "hud_threshold": 0.60,
    "minimum_confidence": 0.70,
    "duplicate_cooldown_seconds": 900.0,
    "budget_capacity": 2.0,
    "budget_recovery_per_hour": 1.0,
    "weights": {
        "importance": 0.30,
        "confidence": 0.25,
        "relevance": 0.20,
        "novelty": 0.15,
        "social_value": 0.05,
        "urgency": 0.15,
        "interruption_cost": -0.20,
    },
}


class CompanionEngine:
    """Event-driven, silence-first policy using the shared event, state and voice services."""

    def __init__(
        self,
        events: EventBus,
        state,
        voice,
        *,
        config: dict | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.monotonic,
        persistence_path: Path | None = None,
    ):
        self.events, self.state, self.voice = events, state, voice
        self.logger = logger or logging.getLogger("jarvis.companion")
        self.clock, self.persistence_path = clock, persistence_path
        self.config: dict[str, Any] = self._validated_config(config or {})
        self._lock = threading.RLock()
        self._recent: dict[str, float] = {}
        self._coding_failures: deque[tuple[float, str]] = deque(maxlen=64)
        self._metrics: Counter[str] = Counter()
        self._score_total = 0.0
        self._budget, self._budget_updated = self.config["budget_capacity"], self.clock()
        self._unsubscribe: Callable[[], None] | None = None
        self._running = False
        self._last_intervention: dict[str, Any] | None = None
        self._load()

    @staticmethod
    def _validated_config(overrides: dict) -> dict[str, Any]:
        config = dict(DEFAULT_CONFIG)
        config["weights"] = dict(DEFAULT_CONFIG["weights"])
        for key, value in overrides.items():
            if key in config:
                config[key] = value
        if str(config["mode"]).lower() not in {x.value for x in CompanionMode}:
            config["mode"] = CompanionMode.NORMAL.value
        for key in ("speak_threshold", "hud_threshold", "minimum_confidence"):
            try:
                config[key] = max(0.0, min(1.0, float(config[key])))
            except (TypeError, ValueError):
                config[key] = DEFAULT_CONFIG[key]
        for key in ("duplicate_cooldown_seconds", "budget_capacity", "budget_recovery_per_hour"):
            try:
                config[key] = max(0.0, float(config[key]))
            except (TypeError, ValueError):
                config[key] = DEFAULT_CONFIG[key]
        if not isinstance(config["weights"], dict):
            config["weights"] = dict(DEFAULT_CONFIG["weights"])
        return config

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._unsubscribe = self.events.subscribe("*", self._on_event)
            self._running = True
        self.state.set("companion", self.snapshot(), source="companion")

    def stop(self) -> None:
        with self._lock:
            if self._unsubscribe:
                self._unsubscribe()
            self._unsubscribe, self._running = None, False
            self._persist()

    def set_mode(self, mode: CompanionMode | str) -> None:
        value = mode.value if isinstance(mode, CompanionMode) else str(mode).lower()
        with self._lock:
            self.config["mode"] = CompanionMode(value).value
        self.state.set("companion", self.snapshot(), source="companion")

    def _on_event(self, event: Event) -> None:
        if event.source == "companion" or not self._running:
            return
        try:
            candidate = self._candidate_from(event)
            if candidate:
                self.evaluate(candidate)
        except Exception as exc:
            with self._lock:
                self._metrics["errors"] += 1
            self.logger.exception(
                "companion.event_failed", extra={"topic": event.topic, "error_type": type(exc).__name__}
            )

    def _candidate_from(self, event: Event) -> InterventionCandidate | None:
        mode = CompanionMode(self.config["mode"])
        coding = bool(self.config["coding_enabled"]) or mode == CompanionMode.CODING_COPILOT
        trading = bool(self.config["trading_enabled"]) or mode == CompanionMode.TRADING_COPILOT
        if trading and event.topic in {"browser.changed", "window.changed"}:
            context = " ".join(str(event.payload.get(key, "")) for key in ("url", "title", "window")).casefold()
            if "tradingview" in context:
                return InterventionCandidate(
                    "trading_context",
                    event.source,
                    "trading",
                    "TradingView è attivo. Posso analizzare il contesto visibile senza eseguire ordini.",
                    0.72,
                    max(0.7, event.confidence),
                    0.9,
                    0.7,
                    0,
                    0.2,
                    0.35,
                    False,
                    "trading:context",
                )
        coding_topics = {
            "test.failed",
            "build.failed",
            "task.failed",
            "dependency.failed",
            "process.crashed",
            "traceback.detected",
        }
        if event.topic not in coding_topics or not coding:
            return None
        signature = str(event.payload.get("signature") or event.payload.get("traceback") or "unknown")[:500]
        now = self.clock()
        with self._lock:
            self._coding_failures.append((now, signature))
            count = sum(value == signature for stamp, value in self._coding_failures if now - stamp <= 900)
        threshold = 3 if event.topic == "test.failed" else 1
        if count < threshold:
            return None
        digest = hashlib.sha256(signature.encode("utf-8", "replace")).hexdigest()[:16]
        return InterventionCandidate(
            "repeated_test_failure",
            event.source,
            "coding",
            "È stato rilevato un errore nel flusso di sviluppo. Posso analizzare traceback, dipendenze e test prima della prossima modifica.",
            0.95,
            max(0.7, event.confidence),
            1,
            1,
            0,
            0.55,
            0.20,
            False,
            f"coding:test-failure:{digest}",
        )

    def evaluate(self, candidate: InterventionCandidate) -> Decision:
        started, now = time.perf_counter(), self.clock()
        with self._lock:
            mode = CompanionMode(self.config["mode"])
            self._recover_budget(now)
            fingerprint = (
                candidate.fingerprint
                or hashlib.sha256(f"{candidate.category}:{candidate.reason}:{candidate.message}".encode()).hexdigest()[
                    :20
                ]
            )
            duplicate = now - self._recent.get(fingerprint, float("-inf")) < self.config["duplicate_cooldown_seconds"]
            score = self._score(candidate)
            self._score_total += score
            self._metrics["candidates"] += 1
            if not self.config["enabled"] or mode in {CompanionMode.PASSIVE, CompanionMode.DO_NOT_DISTURB}:
                decision, reason = Decision.SILENCE, "disabled_or_passive"
            elif candidate.confidence < self.config["minimum_confidence"]:
                decision, reason = Decision.SILENCE, "low_confidence"
            elif duplicate:
                decision, reason = Decision.SILENCE, "duplicate"
                self._metrics["duplicate_suppressions"] += 1
            elif mode == CompanionMode.FOCUS and not candidate.critical:
                decision, reason = (
                    Decision.HUD_ONLY if score >= self.config["hud_threshold"] else Decision.SILENCE
                ), "focus"
            elif score < self.config["hud_threshold"]:
                decision, reason = Decision.SILENCE, "below_hud_threshold"
            elif score < self.config["speak_threshold"] or (self._budget < 1 and not candidate.critical):
                decision, reason = Decision.HUD_ONLY, "threshold_or_budget"
            elif self.voice.state in {VoiceState.LISTENING, VoiceState.SPEAKING}:
                decision, reason = Decision.HUD_ONLY, "voice_busy"
            else:
                decision, reason = (Decision.SPEAK_HIGH_PRIORITY if candidate.critical else Decision.SPEAK), "approved"
                self._budget = max(0.0, self._budget - (0.5 if candidate.critical else 1.0))
            if decision != Decision.SILENCE:
                self._recent[fingerprint] = now
            if decision in {Decision.SPEAK, Decision.SPEAK_HIGH_PRIORITY}:
                priority = SpeechPriority.HIGH if candidate.critical else SpeechPriority.NORMAL
                request_id = self.voice.submit(candidate.message, priority=priority, interruptible=True)
                self._last_intervention = {
                    "message": candidate.message,
                    "reason": candidate.reason,
                    "category": candidate.category,
                    "request_id": request_id,
                    "timestamp_monotonic": now,
                }
                self._metrics["spontaneous_interventions"] += 1
                self.state.set("companion_pending_context", dict(self._last_intervention), source="companion")
            else:
                self._metrics["silence_decisions" if decision == Decision.SILENCE else "suppressed_interventions"] += 1
            self._metrics["decision_latency_ms_total"] += int((time.perf_counter() - started) * 1000)
            record = {
                "candidate_score": round(score, 4),
                "confidence": candidate.confidence,
                "decision": decision.value,
                "reason": reason,
                "category": candidate.category,
                "cooldown": duplicate,
                "budget": round(self._budget, 3),
            }
        self.logger.info("companion.decision", extra=record)
        self.events.publish(
            "companion.decision",
            record,
            source="companion",
            confidence=candidate.confidence,
            deduplication_key=fingerprint,
        )
        self.state.set("companion", self.snapshot(), source="companion")
        return decision

    def consume_pending_context(self) -> dict | None:
        with self._lock:
            value, self._last_intervention = self._last_intervention, None
        self.state.set("companion_pending_context", None, source="companion")
        return dict(value) if value else None

    def _score(self, candidate: InterventionCandidate) -> float:
        names = ("importance", "confidence", "relevance", "novelty", "social_value", "urgency", "interruption_cost")
        return max(
            0.0,
            min(
                1.0, sum(float(self.config["weights"].get(name, 0)) * float(getattr(candidate, name)) for name in names)
            ),
        )

    def _recover_budget(self, now: float) -> None:
        elapsed = max(0.0, now - self._budget_updated)
        self._budget = min(
            self.config["budget_capacity"], self._budget + elapsed * self.config["budget_recovery_per_hour"] / 3600
        )
        self._budget_updated = now

    def snapshot(self) -> dict:
        with self._lock:
            metrics: dict[str, float | int] = dict(self._metrics)
            count = metrics.get("candidates", 0)
            metrics["average_proactivity_score"] = round(self._score_total / count, 4) if count else 0.0
            metrics["average_decision_latency_ms"] = round(
                metrics.get("decision_latency_ms_total", 0) / max(1, count), 3
            )
            return {
                "running": self._running,
                "mode": self.config["mode"],
                "coding_enabled": bool(self.config["coding_enabled"]),
                "trading_enabled": bool(self.config["trading_enabled"]),
                "budget": round(self._budget, 3),
                "last_intervention": self._last_intervention,
                "metrics": metrics,
            }

    def _load(self) -> None:
        if not self.persistence_path or not self.persistence_path.exists():
            return
        try:
            data = json.loads(self.persistence_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("config"), dict):
                self.config = self._validated_config(data["config"])
        except (OSError, json.JSONDecodeError):
            self.logger.warning("companion.persistence_invalid")

    def _persist(self) -> None:
        if not self.persistence_path:
            return
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.persistence_path.with_suffix(self.persistence_path.suffix + ".tmp")
            temporary.write_text(json.dumps({"config": self.config}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.persistence_path)
        except OSError:
            self.logger.exception("companion.persistence_failed")
