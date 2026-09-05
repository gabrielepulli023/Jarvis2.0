"""Evidence-based, advisory decision memory on the canonical MemoryStore."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping

from settings_store import get_setting
from jarvis_core.logging import redact
from .store import MemoryKind, MemoryStore


class DecisionOutcome(StrEnum):
    VERIFIED_SUCCESS = "verified_success"
    SUCCESS_UNVERIFIED = "success_unverified"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class CausalityLevel(StrEnum):
    OBSERVED_ASSOCIATION = "observed_association"
    SUPPORTED_CAUSE = "supported_cause"
    VERIFIED_OUTCOME = "verified_outcome"


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    fingerprint: str
    objective: str
    intent_kind: str = ""
    strategy: str = ""
    semantic_action: str = ""
    target_type: str = ""
    risk_hint: str = "safe"
    candidate_skills: tuple[str, ...] = ()
    selected_skills: tuple[str, ...] = ()
    selected_capabilities: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    decision_reasons: tuple[str, ...] = ()
    outcome: DecisionOutcome = DecisionOutcome.PARTIAL
    verified: bool = False
    confidence: float = 0.0
    decision_confidence: float = 0.0
    outcome_confidence: float = 0.0
    observed_event_codes: tuple[str, ...] = ()
    fallback_used: tuple[str, ...] = ()
    recovery_count: int = 0
    occurrences: int = 1
    causality: CausalityLevel = CausalityLevel.OBSERVED_ASSOCIATION
    source: str = "decision_memory"


_SENSITIVE = re.compile(r"(?i)(password|api[_ -]?key|token|authorization|credit card|secret)\s*[:=]?")
_OUTCOME_VALUES = {item.value for item in DecisionOutcome}
_REASONS = {"timeout", "permission_denied", "precondition_failed", "verification_failed", "unverified_side_effect", "action_error", "fallback_recovered", "cancelled", "unknown_action"}


class DecisionMemory:
    """Thread-safe adapter; it owns no executor, router, DB or second cache."""

    MAX_PENDING = 32

    def __init__(self, memory: MemoryStore, *, mission_store=None, settings_get=get_setting):
        self.memory = memory
        self.mission_store = mission_store
        self._get = settings_get
        self._lock = threading.RLock()

    def _enabled(self) -> bool:
        return not bool(self._get("privacy_mode", False))

    @staticmethod
    def fingerprint(objective: str, decision: Mapping[str, Any] | None = None) -> str:
        payload = {"objective_key": DecisionMemory.objective_key(objective),
                   "decision": {key: dict(decision or {}).get(key, "") for key in ("intent_kind", "strategy", "semantic_action", "target_type", "risk_hint", "candidate_skills")}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]

    @staticmethod
    def objective_key(objective: str) -> str:
        return hashlib.sha256(re.sub(r"\s+", " ", str(objective or "").strip().lower())[:500].encode()).hexdigest()[:24]

    @staticmethod
    def decision_fingerprint(objective: str, decision: Mapping[str, Any] | None = None) -> str:
        return DecisionMemory.fingerprint(objective, decision)

    @staticmethod
    def _bounded_tuple(values, limit):
        result = []
        for value in values or ():
            item = str(value)[:100]
            if item.strip() and item not in result:
                result.append(item)
            if len(result) >= limit:
                break
        return tuple(result)

    def observe_decision(self, decision, *, objective: str | None = None) -> dict | None:
        if not self._enabled():
            return None
        objective = str(redact(objective if objective is not None else getattr(decision, "original_user_text", "")))[:500]
        payload = {
            "objective_key": self.objective_key(objective),
            "fingerprint": self.fingerprint(objective, {"intent_kind": str(getattr(decision, "intent_kind", "")), "strategy": str(getattr(decision, "strategy", "")), "semantic_action": getattr(decision, "semantic_action", ""), "target_type": getattr(decision, "target_type", ""), "risk_hint": getattr(decision, "risk_hint", ""), "candidate_skills": getattr(decision, "candidate_skills", ())}),
            "intent_kind": str(getattr(decision, "intent_kind", "")), "strategy": str(getattr(decision, "strategy", "")),
            "semantic_action": str(getattr(decision, "semantic_action", "") or "")[:100],
            "target_type": str(getattr(decision, "target_type", "") or "")[:100],
            "risk_hint": str(getattr(decision, "risk_hint", "safe"))[:40],
            "confidence": max(0.0, min(1.0, float(getattr(decision, "confidence", 0.0)))),
            "candidate_skills": self._bounded_tuple(getattr(decision, "candidate_skills", ()), 8),
            "decision_reasons": self._bounded_tuple(getattr(decision, "reasons", ()), 8),
        }
        with self._lock:
            pending = self.memory.working.namespace("decision.pending.")
            if len(pending) >= self.MAX_PENDING and f"decision.pending.{payload['fingerprint']}" not in pending:
                oldest = min(pending, key=lambda key: (self.memory.working.inspect(key) or {}).get("updated_at", float("inf")))
                self.memory.working.delete(oldest)
            self.memory.working.set(f"decision.pending.{payload['fingerprint']}", payload, ttl=1200, source="decision_memory")
        return payload

    def resolve_pending(self, objective: str) -> dict | None:
        key = self.objective_key(objective)
        with self._lock:
            candidates = [(name, value) for name, value in self.memory.working.namespace("decision.pending.").items() if value.get("objective_key") == key]
            if not candidates:
                return None
            name, value = max(candidates, key=lambda item: ((self.memory.working.inspect(item[0]) or {}).get("updated_at", float("-inf")), str(item[0])))
            self.memory.working.delete(name)
            return value

    def _record_from(self, data: Mapping[str, Any]) -> DecisionRecord:
        objective = str(redact(data.get("objective", "")))[:500]
        if _SENSITIVE.search(objective) or _SENSITIVE.search(json.dumps(data, ensure_ascii=False, default=str)):
            raise ValueError("sensitive decision evidence rejected")
        outcome = str(data.get("outcome", DecisionOutcome.PARTIAL.value)).lower()
        if outcome not in _OUTCOME_VALUES:
            outcome = DecisionOutcome.PARTIAL.value
        verified = bool(data.get("verified", False))
        if outcome == DecisionOutcome.VERIFIED_SUCCESS.value:
            verified = True
        reason_codes = tuple(code for code in self._bounded_tuple(data.get("reason_codes", ()), 8) if code in _REASONS)
        decision_reasons = self._bounded_tuple(data.get("decision_reasons", ()), 8)
        decision_confidence = max(0.0, min(1.0, float(data.get("decision_confidence", data.get("confidence", 0.0)))))
        event_reasons = {"task.timeout": "timeout", "task.precondition_failed": "precondition_failed",
                         "task.unverified": "unverified_side_effect", "task.recovered": "fallback_recovered",
                         "mission.cancelled": "cancelled"}
        reason_codes = tuple(dict.fromkeys((*reason_codes, *(event_reasons[event] for event in data.get("observed_event_codes", ()) if event in event_reasons))))[:8]
        return DecisionRecord(
            fingerprint=str(data.get("fingerprint") or self.fingerprint(objective, data))[:64], objective=objective,
            intent_kind=str(data.get("intent_kind", ""))[:60], strategy=str(data.get("strategy", ""))[:60],
            semantic_action=str(data.get("semantic_action", ""))[:100], target_type=str(data.get("target_type", ""))[:60],
            risk_hint=str(data.get("risk_hint", "safe"))[:40], candidate_skills=self._bounded_tuple(data.get("candidate_skills"), 8),
            selected_skills=self._bounded_tuple(data.get("selected_skills"), 12), selected_capabilities=self._bounded_tuple(data.get("selected_capabilities"), 12),
            reason_codes=reason_codes, decision_reasons=decision_reasons, outcome=DecisionOutcome(outcome), verified=verified,
            confidence=decision_confidence, decision_confidence=decision_confidence,
            outcome_confidence=max(0.0, min(1.0, float(data.get("outcome_confidence", data.get("confidence", 0.0))))),
            observed_event_codes=self._bounded_tuple(data.get("observed_event_codes"), 16),
            fallback_used=self._bounded_tuple(data.get("fallback_used"), 8), recovery_count=max(0, min(32, int(data.get("recovery_count", 0)))),
            occurrences=max(1, min(100000, int(data.get("occurrences", 1)))),
            causality=CausalityLevel(str(data.get("causality", CausalityLevel.OBSERVED_ASSOCIATION.value))),
            source=str(data.get("source", "decision_memory"))[:80],
        )

    def record_outcome(self, data: Mapping[str, Any]) -> DecisionRecord | None:
        if not self._enabled():
            return None
        record = self._record_from(data)
        content = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, default=lambda value: value.value)
        result = self.memory.remember_or_increment(
            content, kind=MemoryKind.DECISION, source=record.source, confidence=record.confidence,
            importance=.75 if record.verified else .5,
            metadata={"occurrences": 1, "fingerprint": record.fingerprint},
        )
        return DecisionRecord(**{**asdict(record), "occurrences": result["occurrences"]})

    def record_mission_outcome(self, objective: str, evidence: Mapping[str, Any]) -> DecisionRecord | None:
        pending = self.resolve_pending(objective)
        merged = dict(pending or {})
        merged.update({key: value for key, value in evidence.items() if value not in (None, "", (), [])})
        merged["objective"] = str(objective or "")[:500]
        mission_id = merged.get("mission_id")
        if self.mission_store is not None and mission_id:
            try:
                mission = self.mission_store.get(str(mission_id))
                events = self.mission_store.events(str(mission_id))
                codes = tuple(
                    str(item.get("event", ""))[:80]
                    for item in events
                    if item.get("event") and item.get("event") != "mission.created"
                )[-16:]
                if codes:
                    merged["observed_event_codes"] = codes
                if "mission.cancelled" in codes or (mission and mission.get("status") == "cancelled"):
                    merged["outcome"] = DecisionOutcome.CANCELLED.value
                    merged["reason_codes"] = ("cancelled",)
                elif mission and mission.get("status") == "failed":
                    merged["outcome"] = DecisionOutcome.FAILED.value
                elif "mission.completed" in codes or (mission and mission.get("status") == "completed"):
                    verified = ("task.completed" in codes or "task.recovered" in codes) and "task.unverified" not in codes
                    merged["outcome"] = DecisionOutcome.VERIFIED_SUCCESS.value if verified else DecisionOutcome.SUCCESS_UNVERIFIED.value
                    merged["verified"] = verified
                elif mission and mission.get("status") in {"waiting", "blocked", "precondition_failed"}:
                    merged["outcome"] = DecisionOutcome.BLOCKED.value
                for event, reason in (("task.timeout", "timeout"), ("task.precondition_failed", "precondition_failed"),
                                      ("task.unverified", "unverified_side_effect"), ("task.recovered", "fallback_recovered"),
                                      ("mission.cancelled", "cancelled")):
                    if event in codes:
                        merged.setdefault("reason_codes", ())
                        merged["reason_codes"] = (*merged["reason_codes"], reason)
            except Exception:
                pass
        event_codes = tuple(merged.get("observed_event_codes", ()))
        if event_codes:
            merged["reason_codes"] = tuple(dict.fromkeys((*merged.get("reason_codes", ()), *(code for code in ("timeout", "precondition_failed", "unverified_side_effect", "fallback_recovered", "cancelled") if {"timeout": "task.timeout", "precondition_failed": "task.precondition_failed", "unverified_side_effect": "task.unverified", "fallback_recovered": "task.recovered", "cancelled": "mission.cancelled"}[code] in event_codes))))[:8]
        merged["fingerprint"] = self.fingerprint(merged["objective"], merged)
        return self.record_outcome(merged)

    def record(self, data: Mapping[str, Any]) -> DecisionRecord | None:
        return self.record_outcome(data)

    def recall(self, query: str, limit: int = 20) -> tuple[DecisionRecord, ...]:
        if not self._enabled():
            return ()
        rows = self.memory.search(str(query or "")[:500], kind=MemoryKind.DECISION, limit=min(20, max(1, int(limit))))
        records = []
        for row in rows:
            try:
                value = json.loads(row["content"])
                value["occurrences"] = int((row.get("metadata") or {}).get("occurrences", value.get("occurrences", 1)))
                records.append(self._record_from(value))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        return tuple(records)

    def lessons(self, query: str, limit: int = 20) -> dict[str, Any]:
        records = self.recall(query, limit)
        successes = sum(record.occurrences for record in records if record.outcome is DecisionOutcome.VERIFIED_SUCCESS)
        failures = sum(record.occurrences for record in records if record.outcome is DecisionOutcome.FAILED)
        other = sum(record.occurrences for record in records if record.outcome not in {DecisionOutcome.VERIFIED_SUCCESS, DecisionOutcome.FAILED})
        sample = successes + failures + other
        dominant = max(successes, failures, other)
        if dominant < 2:
            strength = "anecdotal"
        elif dominant < 3:
            strength = "weak"
        else:
            strength = "supported"
        support = min(1.0, dominant / 3.0)
        coherence = (dominant / sample) if sample else 0.0
        return {"sample_size": sample, "verified_successes": successes, "failures": failures, "strength": strength,
                "observed_patterns": ["fallback recovered after a failed attempt" for record in records if record.fallback_used][:8],
                "confidence": max(0.0, min(1.0, ((successes / sample) if sample else 0.0) * support * coherence)), "advisory_only": True}

    def status(self) -> dict[str, Any]:
        if not self._enabled():
            return {"enabled": False, "persistent_records": 0, "pending_decisions": 0}
        rows = self.memory.list_metadata(kind=MemoryKind.DECISION, limit=100000)
        return {"enabled": True, "persistent_records": self.memory.count(kind=MemoryKind.DECISION), "pending_decisions": len(self.memory.working.namespace("decision.pending.")),
                "verified_success_records": sum(json.loads(row["content"]).get("outcome") == DecisionOutcome.VERIFIED_SUCCESS.value for row in rows),
                "failure_records": sum(json.loads(row["content"]).get("outcome") == DecisionOutcome.FAILED.value for row in rows)}
