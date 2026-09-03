from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Callable
from .evidence import ConfidenceEngine, EvidenceEngine
from .graph import Task, TaskGraph, TaskStatus
from .store import MissionStore
from jarvis_core.recovery import RecoveryEngine, RecoveryStrategy
from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class StepSpec:
    id: str
    label: str
    action: str
    arguments: dict
    expected: dict
    dependencies: frozenset[str] = frozenset()
    timeout: float = 30.0
    max_attempts: int = 3
    risk: str = "safe"
    precondition_action: str | None = None
    precondition_arguments: dict | None = None
    precondition_expected: dict | None = None
    rollback_action: str | None = None
    rollback_arguments: dict | None = None
    fallbacks: tuple[str, ...] = ()


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    @property
    def event(self):
        return self._event


class MissionEngine:
    def __init__(
        self,
        store: MissionStore,
        *,
        evidence: EvidenceEngine | None = None,
        confidence: ConfidenceEngine | None = None,
        memory=None,
        recovery: RecoveryEngine | None = None,
        authorize: Callable[[str, dict, str], str] | None = None,
    ):
        self.store = store
        self.evidence = evidence or EvidenceEngine()
        self.confidence = confidence or ConfidenceEngine()
        self.memory = memory
        self.recovery = recovery
        self.authorize = authorize or (lambda action, arguments, risk: "allow")
        self._actions: dict[str, Callable[..., dict]] = {}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-mission")
        self._tokens: set[CancellationToken] = set()
        self._token_lock = threading.RLock()

    def register_action(self, name: str, action: Callable[..., dict]) -> None:
        self._actions[name] = action

    def build(self, specs: list[StepSpec]) -> TaskGraph:
        ids = {x.id for x in specs}
        if len(ids) != len(specs):
            raise ValueError("step ids must be unique")
        return TaskGraph([Task(x.id, x.label, set(x.dependencies), max_attempts=x.max_attempts) for x in specs])

    def run(
        self,
        objective: str,
        specs: list[StepSpec],
        token: CancellationToken | None = None,
        *,
        dry_run: bool = False,
        confirmed_steps: set[str] | None = None,
    ) -> dict:
        token = token or CancellationToken()
        with self._token_lock:
            self._tokens.add(token)
        graph = self.build(specs)
        mission_id = self.store.create(objective, graph)
        by_id = {x.id: x for x in specs}
        if dry_run:
            self.store.save(
                mission_id,
                graph,
                status="dry_run",
                checkpoint={
                    "steps": [
                        {
                            "id": x.id,
                            "action": x.action,
                            "arguments": x.arguments,
                            "risk": x.risk,
                            "expected": x.expected,
                        }
                        for x in specs
                    ]
                },
                event="mission.dry_run",
            )
            with self._token_lock:
                self._tokens.discard(token)
            return self.store.get(mission_id) or {}
        confirmed_steps = set(confirmed_steps or ())
        waiting = False
        while True:
            if token.cancelled:
                graph.cancel()
                self.store.save(mission_id, graph, status="cancelled", event="mission.cancelled")
                break
            ready = graph.ready()
            if not ready:
                break
            for task in ready:
                if token.cancelled:
                    break
                spec = by_id[task.id]
                permission = self.authorize(spec.action, dict(spec.arguments), spec.risk)
                if permission == "confirm" and spec.id not in confirmed_steps:
                    graph.wait_for_user(task.id, "confirmation required")
                    self.store.save(
                        mission_id,
                        graph,
                        status="waiting_user",
                        checkpoint={"task": task.id, "risk": spec.risk},
                        event="task.waiting_user",
                    )
                    waiting = True
                    break
                if permission == "deny":
                    graph.skip(task.id, "permission denied")
                    self.store.save(
                        mission_id,
                        graph,
                        status="running",
                        checkpoint={"task": task.id, "risk": spec.risk},
                        event="task.skipped",
                    )
                    continue
                if spec.precondition_action:
                    precondition = self._actions.get(spec.precondition_action)
                    if precondition is None:
                        graph.skip(task.id, "unknown precondition")
                        self.store.save(
                            mission_id,
                            graph,
                            status="running",
                            checkpoint={"task": task.id},
                            event="task.precondition_failed",
                        )
                        continue
                    pre_result = dict(precondition(**dict(spec.precondition_arguments or {})) or {})
                    pre_proof = self.evidence.verify(
                        spec.precondition_action, spec.precondition_expected or {}, pre_result
                    )
                    if not self.confidence.sufficient([pre_proof]):
                        graph.skip(task.id, "precondition failed")
                        self.store.save(
                            mission_id,
                            graph,
                            status="running",
                            checkpoint={"task": task.id, "evidence": pre_proof.as_dict()},
                            event="task.precondition_failed",
                        )
                        continue
                graph.start(task.id)
                self.store.save(
                    mission_id,
                    graph,
                    status="running",
                    checkpoint={"task": task.id, "attempt": task.attempts},
                    event="task.started",
                )
                action = self._actions.get(spec.action)
                if action is None:
                    graph.fail(task.id, f"unknown action: {spec.action}")
                    self.store.save(
                        mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.failed"
                    )
                    continue
                future = self._pool.submit(action, **dict(spec.arguments))
                try:
                    result = future.result(timeout=max(0.01, spec.timeout))
                except TimeoutError:
                    future.cancel()
                    graph.fail(task.id, f"timeout after {spec.timeout}s")
                    self.store.save(
                        mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.timeout"
                    )
                    continue
                except Exception as exc:
                    graph.fail(task.id, redact(f"{type(exc).__name__}: {exc}"))
                    self.store.save(
                        mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.failed"
                    )
                    continue
                proof = self.evidence.verify(spec.action, spec.expected, dict(result or {}))
                if self.confidence.sufficient([proof]):
                    graph.complete(task.id, dict(result or {}), [proof.as_dict()])
                    event = "task.completed"
                else:
                    recovered = self._recover(spec, token)
                    if recovered is not None:
                        recovered_result, recovered_proof = recovered
                        proof = recovered_proof
                        graph.complete(task.id, recovered_result, [recovered_proof.as_dict()])
                        event = "task.recovered"
                    else:
                        graph.fail(task.id, f"verification failed ({proof.confidence:.2f}): {proof.observation}")
                        event = "task.unverified"
                self.store.save(
                    mission_id,
                    graph,
                    status="running",
                    checkpoint={"task": task.id, "evidence": proof.as_dict()},
                    event=event,
                )
            if waiting:
                break
        status = self._critic_status(graph)
        rollback = []
        if status == "failed":
            rollback = self._rollback(specs, graph)
        self.store.save(
            mission_id,
            graph,
            status=status,
            checkpoint={"progress": graph.progress(), "rollback": rollback},
            event=f"mission.{status}",
        )
        if status == "completed" and self.memory is not None:
            procedure = " -> ".join(f"{spec.action}({spec.arguments})" for spec in specs)
            self.memory.remember(
                procedure,
                kind="procedural",
                source="mission",
                confidence=1,
                importance=0.8,
                metadata={"objective": objective, "mission_id": mission_id},
            )
        result = self.store.get(mission_id) or {}
        with self._token_lock:
            self._tokens.discard(token)
        return result

    def _recover(self, spec: StepSpec, token: CancellationToken):
        if self.recovery is None or not spec.fallbacks:
            return None
        latest: dict[str, dict] = {"result": {}}
        strategies = []
        for name in spec.fallbacks:
            action = self._actions.get(name)
            if action is None:
                continue

            def execute(action=action):
                latest["result"] = dict(action(**dict(spec.arguments)) or {})
                return latest["result"]

            def verify(_after, result, name=name):
                return self.confidence.sufficient([self.evidence.verify(name, spec.expected, result)])

            strategies.append(RecoveryStrategy(name, execute, verify))
        if not strategies:
            return None
        outcome = self.recovery.run(
            spec.action, strategies, lambda: {"result": dict(latest["result"])}, cancellation=token.event
        )
        if not outcome.success:
            return None
        result = dict(latest["result"])
        proof = self.evidence.verify(outcome.strategy or spec.action, spec.expected, result)
        return result, proof

    def _rollback(self, specs: list[StepSpec], graph: TaskGraph) -> list[dict]:
        rows = []
        for spec in reversed(specs):
            if graph.tasks[spec.id].status != TaskStatus.COMPLETED or not spec.rollback_action:
                continue
            action = self._actions.get(spec.rollback_action)
            if action is None:
                rows.append({"step": spec.id, "success": False, "error": "unknown rollback"})
                continue
            try:
                result = dict(action(**dict(spec.rollback_arguments or {})) or {})
                rows.append(
                    {
                        "step": spec.id,
                        "success": bool(result.get("success", result.get("successo", False))),
                        "result": result,
                    }
                )
            except Exception as exc:
                    rows.append({"step": spec.id, "success": False, "error": redact(f"{type(exc).__name__}: {exc}")})
        return rows

    @staticmethod
    def _critic_status(graph: TaskGraph) -> str:
        statuses = {x.status for x in graph.tasks.values()}
        if graph.cancelled:
            return "cancelled"
        if TaskStatus.WAITING_USER in statuses:
            return "waiting_user"
        if statuses == {TaskStatus.COMPLETED} or not statuses:
            return "completed"
        if statuses and statuses <= {TaskStatus.COMPLETED, TaskStatus.SKIPPED}:
            return "completed_with_skips"
        if TaskStatus.FAILED in statuses:
            return "failed"
        if TaskStatus.BLOCKED in statuses:
            return "blocked"
        return "incomplete"

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def cancel_all(self) -> int:
        with self._token_lock:
            tokens = tuple(self._tokens)
        for token in tokens:
            token.cancel()
        return len(tokens)

    def explain(self, mission_id: str | None = None) -> dict:
        if mission_id is None:
            recent = self.store.recent(1)
            if not recent:
                return {"success": False, "message": "Non ci sono missioni da spiegare."}
            mission_id = recent[0]["id"]
        mission = self.store.get(str(mission_id))
        if mission is None:
            return {"success": False, "message": "Missione non trovata."}
        graph = mission.get("graph", {})
        tasks = graph.get("tasks", []) if isinstance(graph, dict) else []
        current = next(
            (
                {
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "status": row.get("status"),
                    "reason": row.get("error"),
                }
                for row in tasks
                if row.get("status") in {"running", "waiting_user", "failed", "blocked"}
            ),
            None,
        )
        completed = sum(1 for row in tasks if row.get("status") == "completed")
        explanation = {
            "mission_id": mission["id"],
            "task": mission["objective"],
            "status": mission["status"],
            "step": current,
            "reason": (
                None
                if current is None
                else current.get("reason") or "Esecuzione del prossimo passo con dipendenze soddisfatte."
            ),
            "expected_result": mission.get("checkpoint", {}).get("expected"),
            "progress": {"completed": completed, "total": len(tasks)},
            "recent_events": self.store.events(mission["id"], 10),
        }
        return {"success": True, "message": self._explain_text(explanation), "data": explanation}

    @staticmethod
    def _explain_text(value):
        step = value.get("step")
        detail = f" Passo corrente: {step.get('label') or step.get('id')} ({step.get('status')})." if step else ""
        return f"Missione: {value['task']}. Stato: {value['status']}.{detail} Progresso: {value['progress']['completed']} di {value['progress']['total']}."
