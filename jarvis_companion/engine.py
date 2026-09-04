from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, replace
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
    proposal: ProactiveProposal | None = None


@dataclass(frozen=True, slots=True)
class ProactiveProposal:
    """Non-executable context for the normal conversational router."""

    intent: str
    description: str


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
MAX_RECENT_FINGERPRINTS = 256
MAX_MUTED_CATEGORIES = 32


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
        notifications=None,
        context_provider: Callable[[], dict] | None = None,
    ):
        self.events, self.state, self.voice = events, state, voice
        self.logger = logger or logging.getLogger("jarvis.companion")
        self.clock, self.persistence_path = clock, persistence_path
        self.notifications, self.context_provider = notifications, context_provider
        self._allow_legacy_enabled = "enabled" not in (config or {})
        self.config: dict[str, Any] = self._validated_config(config or {})
        self._lock = threading.RLock()
        self._persist_lock = threading.Lock()
        self._recent: dict[str, float] = {}
        self._coding_failures: deque[tuple[float, str]] = deque(maxlen=64)
        self._metrics: Counter[str] = Counter()
        self._score_total = 0.0
        self._budget, self._budget_updated = self.config["budget_capacity"], self.clock()
        self._unsubscribe: Callable[[], None] | None = None
        self._running = False
        self._last_intervention: dict[str, Any] | None = None
        self._muted_categories: set[str] = set()
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

    def set_enabled(self, enabled: bool) -> None:
        value = self._parse_bool(enabled)
        with self._lock:
            self.config["enabled"] = value
        self._persist()
        self.state.set("companion", self.snapshot(), source="companion")

    def status(self) -> dict:
        return self.snapshot()

    def mute_category(self, category: str) -> None:
        with self._lock:
            normalized = str(category).strip().casefold()[:64]
            if normalized:
                self._muted_categories.add(normalized)
                self._muted_categories = set(sorted(self._muted_categories)[:MAX_MUTED_CATEGORIES])
        self._persist()

    def unmute_category(self, category: str) -> None:
        with self._lock:
            self._muted_categories.discard(str(category).strip().casefold()[:64])
        self._persist()

    @staticmethod
    def _parse_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"true", "on", "1", "si", "sì", "yes"}:
            return True
        if normalized in {"false", "off", "0", "no"}:
            return False
        raise ValueError("enabled deve essere un booleano esplicito")

    def set_mode(self, mode: CompanionMode | str) -> None:
        value = mode.value if isinstance(mode, CompanionMode) else str(mode).lower()
        with self._lock:
            self.config["mode"] = CompanionMode(value).value
        self._persist()
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
        system = {
            "system.disk_pressure": ("disk_pressure", "Il disco di sistema è quasi pieno.", .72, .82, .45, False),
            "system.disk_critical": ("disk_critical", "Il disco di sistema è in condizioni critiche.", .95, .95, .8, True),
            "system.memory_pressure": ("memory_pressure", "La memoria RAM è molto utilizzata.", .68, .82, .4, False),
            "system.memory_critical": ("memory_critical", "La memoria RAM è in condizioni critiche.", .9, .95, .75, True),
            "system.battery_low": ("battery_low", "La batteria è scarica. Collega l'alimentazione.", .78, .95, .7, False),
            "system.battery_critical": ("battery_critical", "La batteria è quasi esaurita. Collega subito l'alimentazione.", 1., .99, .98, True),
        }
        if event.topic in system:
            reason, message, importance, confidence, urgency, critical = system[event.topic]
            proposals = {
                "memory_pressure": ProactiveProposal("inspect_memory_usage", "Controllare quali processi stanno usando più RAM"),
                "memory_critical": ProactiveProposal("inspect_memory_usage", "Controllare quali processi stanno usando più RAM"),
                "disk_pressure": ProactiveProposal("inspect_disk_usage", "Controllare lo spazio disponibile sul disco"),
                "disk_critical": ProactiveProposal("inspect_disk_usage", "Controllare lo spazio disponibile sul disco"),
            }
            return InterventionCandidate(reason, event.source, "system", message, importance,
                                         event.confidence, 1.0, 1.0, 0, urgency, .2, critical,
                                         f"system:{reason}", proposals.get(reason))
        hardware = {
            "device.connected": ("device_connected", "È stato collegato un dispositivo.", .45, .82, .1),
            "device.disconnected": ("device_disconnected", "Un dispositivo è stato scollegato.", .62, .88, .35),
            "network.changed": ("network_changed", "La connettività di rete è cambiata.", .35, .78, .1),
            "audio_devices.changed": ("audio_changed", "I dispositivi audio disponibili sono cambiati.", .3, .8, .05),
            "monitors.changed": ("monitors_changed", "La configurazione dei monitor è cambiata.", .42, .84, .15),
        }
        if event.topic in hardware:
            reason, message, importance, confidence, urgency = hardware[event.topic]
            return InterventionCandidate(reason, event.source, "hardware", message, importance,
                                         event.confidence, .8, .8, 0, urgency, .35, False,
                                         f"hardware:{reason}")
        if trading and event.topic in {"browser.changed", "window.changed"}:
            context = " ".join(str(event.payload.get(key, "")) for key in ("url", "title", "window")).casefold()
            if "tradingview" in context:
                return InterventionCandidate(
                    "trading_context",
                    event.source,
                    "trading",
                    "TradingView è attivo. Posso analizzare il contesto visibile senza eseguire ordini.",
                    0.72,
                    event.confidence,
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
            event.confidence,
            1,
            1,
            0,
            0.55,
            0.20,
            False,
            f"coding:test-failure:{digest}",
            ProactiveProposal("inspect_failure_context", "Controllare il contesto dell'errore e i test correlati"),
        )

    def evaluate(self, candidate: InterventionCandidate) -> Decision:
        started, now = time.perf_counter(), self.clock()
        fingerprint = candidate.fingerprint or hashlib.sha256(
            f"{candidate.category}:{candidate.reason}:{candidate.message}".encode("utf-8", "replace")
        ).hexdigest()[:20]
        with self._lock:
            self._prune_recent(now)
            mode = CompanionMode(self.config["mode"])
            duplicate = now - self._recent.get(fingerprint, float("-inf")) < self.config["duplicate_cooldown_seconds"]
            cheap_reason = None
            if not self.config["enabled"] or mode in {CompanionMode.PASSIVE, CompanionMode.DO_NOT_DISTURB}:
                cheap_reason = "disabled_or_passive"
            elif candidate.category.casefold() in self._muted_categories:
                cheap_reason = "muted_category"
            elif candidate.confidence < self.config["minimum_confidence"]:
                cheap_reason = "low_confidence"
            elif duplicate:
                cheap_reason = "duplicate"
        if cheap_reason:
            return self._record_suppressed(candidate, cheap_reason, fingerprint, duplicate, started, now)
        if self.context_provider and self._score(candidate) >= self.config["hud_threshold"]:
            try:
                candidate = self._contextualize_candidate(candidate, self.context_provider())
            except Exception:
                with self._lock:
                    self._metrics["errors"] += 1
        with self._lock:
            mode = CompanionMode(self.config["mode"])
            self._recover_budget(now)
            self._prune_recent(now)
            fingerprint = fingerprint
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
                self._prune_recent(now)
            if decision == Decision.HUD_ONLY and self.notifications is not None:
                self.notifications.notify("JARVIS", candidate.message, "warning" if candidate.urgency >= .5 else "info")
            if decision in {Decision.SPEAK, Decision.SPEAK_HIGH_PRIORITY}:
                if self.notifications is not None:
                    self.notifications.notify("JARVIS", candidate.message, "warning" if candidate.critical else "info")
                priority = SpeechPriority.HIGH if candidate.critical else SpeechPriority.NORMAL
                request_id = self.voice.submit(candidate.message, priority=priority, interruptible=True)
                self._last_intervention = {
                    "message": candidate.message,
                    "reason": candidate.reason,
                    "category": candidate.category,
                    "request_id": request_id,
                    "timestamp_monotonic": now,
                    "proposal": None if candidate.proposal is None else {
                        "intent": candidate.proposal.intent,
                        "description": candidate.proposal.description[:240],
                    },
                }
                self._metrics["spontaneous_interventions"] += 1
                self.state.set("companion_pending_context", dict(self._last_intervention), source="companion")
            else:
                self._metrics["silence_decisions" if decision == Decision.SILENCE else "suppressed_interventions"] += 1
            if decision == Decision.HUD_ONLY:
                self._metrics["hud_interventions"] += 1
            if decision in {Decision.SPEAK, Decision.SPEAK_HIGH_PRIORITY}:
                self._metrics["spoken_interventions"] += 1
            if decision == Decision.SPEAK_HIGH_PRIORITY:
                self._metrics["critical_interventions"] += 1
            if reason == "low_confidence":
                self._metrics["low_confidence_suppressions"] += 1
            if reason == "focus":
                self._metrics["focus_suppressions"] += 1
            if reason == "voice_busy":
                self._metrics["voice_busy_suppressions"] += 1
            if reason == "threshold_or_budget" and self._budget < 1:
                self._metrics["budget_suppressions"] += 1
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

    def _record_suppressed(self, candidate, reason, fingerprint, duplicate, started, now):
        with self._lock:
            self._metrics["candidates"] += 1
            self._metrics["silence_decisions"] += 1
            if duplicate:
                self._metrics["duplicate_suppressions"] += 1
            if reason == "low_confidence":
                self._metrics["low_confidence_suppressions"] += 1
            self._metrics["decision_latency_ms_total"] += int((time.perf_counter() - started) * 1000)
            record = {"candidate_score": 0.0, "confidence": candidate.confidence, "decision": Decision.SILENCE.value,
                      "reason": reason, "category": candidate.category, "cooldown": duplicate,
                      "budget": round(self._budget, 3)}
        self.logger.info("companion.decision", extra=record)
        self.events.publish("companion.decision", record, source="companion", confidence=candidate.confidence,
                            deduplication_key=fingerprint)
        self.state.set("companion", self.snapshot(), source="companion")
        return Decision.SILENCE

    def _prune_recent(self, now: float) -> None:
        cooldown = float(self.config["duplicate_cooldown_seconds"])
        cutoff = now - cooldown
        for key, stamp in list(self._recent.items()):
            if stamp < cutoff:
                self._recent.pop(key, None)
        if len(self._recent) > MAX_RECENT_FINGERPRINTS:
            ordered = sorted(self._recent.items(), key=lambda item: (item[1], item[0]))
            self._recent = dict(ordered[-MAX_RECENT_FINGERPRINTS:])

    @staticmethod
    def _contextualize_candidate(candidate: InterventionCandidate, context: dict | None) -> InterventionCandidate:
        """Apply only bounded decision metadata from an already-plausible context."""
        context = context if isinstance(context, dict) else {}
        relevance, cost, urgency = candidate.relevance, candidate.interruption_cost, candidate.urgency
        active = str((context.get("active_window") or {}).get("title", "")).casefold()
        task = context.get("current_task")
        if candidate.category == "coding" and ("code" in active or "test" in active or task):
            relevance = min(1.0, relevance + .15)
        if candidate.category == "trading" and "tradingview" in active:
            relevance = min(1.0, relevance + .15)
        if candidate.category == "hardware" and task:
            cost = min(1.0, cost + .2)
        if candidate.critical and candidate.category == "system":
            relevance = max(relevance, .95)
        return replace(candidate, relevance=round(relevance, 3), interruption_cost=round(cost, 3), urgency=round(min(1.0, urgency), 3))

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
                "enabled": bool(self.config["enabled"]),
                "mode": self.config["mode"],
                "coding_enabled": bool(self.config["coding_enabled"]),
                "trading_enabled": bool(self.config["trading_enabled"]),
                "budget": round(self._budget, 3),
                "last_intervention": self._last_intervention,
                "metrics": metrics,
                "muted_categories": sorted(self._muted_categories),
            }

    def _load(self) -> None:
        if not self.persistence_path or not self.persistence_path.exists():
            # One-way startup compatibility only; the companion preference
            # file becomes the runtime source of truth after first persist.
            try:
                from settings_store import get_setting
                if self._allow_legacy_enabled:
                    self.config["enabled"] = bool(get_setting("proactive_enabled", True))
            except Exception:
                pass
            return
        try:
            data = json.loads(self.persistence_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("config"), dict):
                self.config = self._validated_config(data["config"])
                raw_categories = data.get("muted_categories", ())
                self._muted_categories = (
                    {str(x).strip().casefold()[:64] for x in sorted(raw_categories, key=str) if isinstance(x, str) and str(x).strip()} 
                    if isinstance(raw_categories, (list, tuple, set)) else set()
                )
                self._muted_categories = set(sorted(self._muted_categories)[:MAX_MUTED_CATEGORIES])
        except (OSError, json.JSONDecodeError):
            self.logger.warning("companion.persistence_invalid")

    def _persist(self) -> None:
        if not self.persistence_path:
            return
        try:
            with self._persist_lock:
                with self._lock:
                    payload = {"config": dict(self.config), "muted_categories": sorted(self._muted_categories)}
                self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.persistence_path.with_suffix(self.persistence_path.suffix + ".tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.persistence_path)
        except OSError:
            self.logger.exception("companion.persistence_failed")
