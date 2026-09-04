from __future__ import annotations
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Callable
from .evidence import ConfidenceEngine, EvidenceEngine
from .graph import Task, TaskGraph, TaskStatus
from .store import MissionStore
from .planner import MissionPlan, PlannedStep
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
        catalog=None,
    ):
        self.store = store
        self.evidence = evidence or EvidenceEngine()
        self.confidence = confidence or ConfidenceEngine()
        self.memory = memory
        self.recovery = recovery
        self.authorize = authorize or (lambda action, arguments, risk: "allow")
        self.catalog = catalog
        self._actions: dict[str, Callable[..., dict]] = {}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-mission")
        self._tokens: set[CancellationToken] = set()
        self._tokens_by_mission: dict[str, CancellationToken] = {}
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
        mission_id: str | None = None,
        existing_graph: TaskGraph | None = None,
        plan_payload: dict | None = None,
        on_step: Callable[[str, str, dict, dict], None] | None = None,
    ) -> dict:
        token = token or CancellationToken()
        with self._token_lock:
            self._tokens.add(token)
        graph = existing_graph or self.build(specs)
        mission_id = mission_id or self.store.create(objective, graph, plan_payload)
        self._tokens_by_mission[mission_id] = token
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
        for task_id in confirmed_steps:
            if task_id in graph.tasks and graph.tasks[task_id].status == TaskStatus.WAITING_USER:
                graph.tasks[task_id].status = TaskStatus.READY
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
                try:
                    arguments = self._resolve_arguments(spec.arguments, graph, task)
                except ValueError as exc:
                    graph.skip(task.id, f"unresolvable output reference: {exc}")
                    self.store.save(mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.blocked")
                    continue
                effective_risk = self._risk(spec.action, spec.risk)
                permission = self.authorize(spec.action, arguments, effective_risk)
                if permission == "confirm" and spec.id not in confirmed_steps:
                    graph.wait_for_user(task.id, "confirmation required")
                    self.store.save(
                        mission_id,
                        graph,
                        status="waiting_user",
                        checkpoint={"task": task.id, "risk": effective_risk, "action": spec.action, "confirmation_mode": "preflight", "mission_id": mission_id},
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
                    pre_arguments = self._resolve_arguments(spec.precondition_arguments or {}, graph, task)
                    pre_permission = self.authorize(spec.precondition_action, pre_arguments, self._risk(spec.precondition_action, "safe"))
                    if pre_permission != "allow":
                        graph.wait_for_user(task.id, "precondition authorization required") if pre_permission == "confirm" else graph.skip(task.id, "precondition permission denied")
                        self.store.save(mission_id, graph, status="waiting_user" if pre_permission == "confirm" else "running", checkpoint={"task": task.id, "precondition": spec.precondition_action}, event="task.precondition_authorization")
                        if pre_permission == "confirm":
                            waiting = True
                            break
                        continue
                    pre_result = dict(precondition(**pre_arguments) or {})
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
                future = self._pool.submit(action, **arguments)
                try:
                    result = future.result(timeout=max(0.01, spec.timeout))
                except TimeoutError:
                    future.cancel()
                    task.status = TaskStatus.NEEDS_VERIFICATION
                    task.error = f"timeout after {spec.timeout}s"
                    self.store.save(
                        mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.timeout"
                    )
                    continue
                except Exception as exc:
                    self._fail(graph, task, spec, redact(f"{type(exc).__name__}: {exc}"))
                    self.store.save(
                        mission_id, graph, status="running", checkpoint={"task": task.id}, event="task.failed"
                    )
                    continue
                if isinstance(result, Mapping) and (result.get("richiede_conferma") or result.get("requires_confirmation")):
                    graph.wait_for_user(task.id, str(result.get("messaggio") or result.get("message") or "confirmation required"))
                    self.store.save(mission_id, graph, status="waiting_user", checkpoint={"task": task.id, "result": dict(result), "action_id": result.get("azione_id") or result.get("action_id"), "confirmation_mode": "executor_pending", "mission_id": mission_id}, event="task.waiting_user")
                    if on_step:
                        on_step(mission_id, spec.action, arguments, dict(result))
                    waiting = True
                    break
                proof = self.evidence.verify(spec.action, spec.expected, dict(result or {}))
                if self.confidence.sufficient([proof]):
                    graph.complete(task.id, dict(result or {}), [proof.as_dict()])
                    event = "task.completed"
                else:
                    recovered = self._recover(spec, token) if self._retry_safe(spec.action) else None
                    if recovered is not None:
                        recovered_result, recovered_proof = recovered
                        proof = recovered_proof
                        graph.complete(task.id, recovered_result, [recovered_proof.as_dict()])
                        event = "task.recovered"
                    else:
                        if self._retry_safe(spec.action):
                            graph.fail(task.id, f"verification failed ({proof.confidence:.2f}): {proof.observation}")
                        else:
                            task.status = TaskStatus.NEEDS_VERIFICATION
                            task.error = f"unverified side effect: {proof.observation}"
                        event = "task.unverified"
                self.store.save(
                    mission_id,
                    graph,
                    status="running",
                    checkpoint={"task": task.id, "evidence": proof.as_dict()},
                    event=event,
                )
                if on_step:
                    on_step(mission_id, spec.action, arguments, dict(result or {}))
            if waiting:
                break
        if token.cancelled:
            graph.cancel()
        status = self._critic_status(graph)
        rollback = []
        if status == "failed":
            rollback = self._rollback(specs, graph)
        final_checkpoint = {"progress": graph.progress(), "rollback": rollback}
        if status == "waiting_user":
            final_checkpoint = {**(self.store.get(mission_id) or {}).get("checkpoint", {}), **final_checkpoint}
        self.store.save(
            mission_id,
            graph,
            status=status,
            checkpoint=final_checkpoint,
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
            self._tokens_by_mission.pop(mission_id, None)
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
            if self.authorize(name, dict(spec.arguments), self._risk(name, "safe")) != "allow":
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

    @classmethod
    def _resolve_arguments(cls, value, graph: TaskGraph, task: Task):
        def resolve(item):
            if isinstance(item, Mapping):
                if set(item) == {"$ref"}:
                    ref = item["$ref"]
                    if not isinstance(ref, Mapping) or not isinstance(ref.get("step"), str):
                        raise ValueError("invalid reference")
                    step_id = ref["step"]
                    if step_id not in task.dependencies or step_id not in graph.tasks:
                        raise ValueError("reference is not an ancestor dependency")
                    source = graph.tasks[step_id]
                    if source.status != TaskStatus.COMPLETED or not isinstance(source.result, Mapping):
                        raise ValueError("referenced step is not completed")
                    current = source.result
                    path = str(ref.get("path", "")).split(".") if ref.get("path") else []
                    if len(path) > 12:
                        raise ValueError("reference path too deep")
                    for part in path:
                        if part in {"", "__class__", "__dict__", "secret", "token", "password"}:
                            raise ValueError("invalid reference path")
                        if isinstance(current, Mapping) and part in current:
                            current = current[part]
                        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                            current = current[int(part)]
                        else:
                            raise ValueError("reference value missing")
                    return current
                return {str(key): resolve(val) for key, val in list(item.items())[:32]}
            if isinstance(item, list):
                return [resolve(val) for val in item[:32]]
            return item
        return resolve(value)

    def _risk(self, action: str, declared: str) -> str:
        row = None
        if self.catalog is not None:
            lookup = getattr(self.catalog, "manifest", None)
            row = lookup(action) if lookup else None
        actual = str((row or {}).get("risk", "safe"))
        order = {"safe": 0, "sensitive": 1, "admin": 2, "destructive": 3, "forbidden": 4}
        return max((str(declared), actual), key=lambda item: order.get(item, 4))

    def _retry_safe(self, action: str) -> bool:
        if self.catalog is None:
            return True
        row = self.catalog.manifest(action)
        effects = (row or {}).get("side_effects")
        return isinstance(effects, (list, tuple)) and len(effects) == 0 or effects == ["none"] or effects == ("none",)

    def _fail(self, graph, task, spec, error):
        if not self._retry_safe(spec.action):
            task.status = TaskStatus.FAILED
            task.attempts = task.max_attempts
            task.error = error
            graph.refresh()
            return
        graph.fail(task.id, error)

    def _rollback(self, specs: list[StepSpec], graph: TaskGraph) -> list[dict]:
        rows = []
        for spec in reversed(specs):
            if graph.tasks[spec.id].status != TaskStatus.COMPLETED or not spec.rollback_action:
                continue
            action = self._actions.get(spec.rollback_action)
            if action is None:
                rows.append({"step": spec.id, "success": False, "error": "unknown rollback"})
                continue
            if self.authorize(spec.rollback_action, dict(spec.rollback_arguments or {}), spec.risk) != "allow":
                rows.append({"step": spec.id, "success": False, "error": "rollback authorization required"})
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

    def _critic_status(self, graph: TaskGraph) -> str:
        statuses = {x.status for x in graph.tasks.values()}
        if graph.cancelled:
            return "cancelled"
        if TaskStatus.WAITING_USER in statuses:
            return "waiting_user"
        if statuses == {TaskStatus.COMPLETED} or not statuses:
            return "completed"
        if statuses and statuses <= {TaskStatus.COMPLETED, TaskStatus.SKIPPED}:
            return "completed_with_skips"
        if TaskStatus.NEEDS_VERIFICATION in statuses:
            return "needs_verification" if self.catalog is not None else "failed"
        if TaskStatus.FAILED in statuses:
            return "failed"
        if TaskStatus.BLOCKED in statuses:
            return "blocked"
        return "incomplete"

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def run_plan(self, plan: MissionPlan, *, executor: Callable[[str, dict], dict], dry_run: bool = False, confirmed_steps: set[str] | None = None, mission_id: str | None = None, on_step: Callable[[str, str, dict, dict], None] | None = None) -> dict:
        specs = [self._spec_from_plan_step(s) for s in plan.steps]
        names = {name for spec in specs for name in (spec.action, spec.precondition_action, spec.rollback_action, *spec.fallbacks) if name}
        for name in names:
            self.register_action(name, lambda _action=name, **kwargs: executor(_action, kwargs))
        return self.run(plan.objective, specs, dry_run=dry_run, confirmed_steps=confirmed_steps, mission_id=mission_id, on_step=on_step, plan_payload=plan.as_dict())

    def prepare(self, plan: MissionPlan) -> str:
        """Persist a validated plan before any executor/orchestrator starts."""
        return self.store.create(plan.objective, self.build([self._spec_from_plan_step(step) for step in plan.steps]), plan.as_dict())

    def accept_confirmed_result(self, mission_id: str, step_id: str, result: dict, *, executor: Callable[[str, dict], dict], on_step=None) -> dict:
        record = self.store.get(str(mission_id))
        if not record:
            raise KeyError(mission_id)
        if record["status"] == "cancelled":
            return record
        checkpoint = record.get("checkpoint") or {}
        if checkpoint.get("task") != step_id or checkpoint.get("confirmation_mode") != "executor_pending" or not checkpoint.get("action_id"):
            raise ValueError("confirmation binding mismatch")
        graph = TaskGraph.from_dict(record["graph"])
        task = graph.tasks.get(str(step_id))
        if task is None or task.status != TaskStatus.WAITING_USER:
            raise ValueError("step is not awaiting confirmation")
        spec = next((step for step in MissionPlan.from_dict(record["plan"]).steps if step.id == step_id), None)
        if spec is None:
            raise ValueError("step unavailable")
        proof = self.evidence.verify(spec.action, dict(spec.expected), dict(result or {}))
        if not self.confidence.sufficient([proof]):
            task.status = TaskStatus.NEEDS_VERIFICATION
            task.error = "confirmed result is unverified"
            self.store.save(mission_id, graph, status="needs_verification", checkpoint={"task": step_id, "evidence": proof.as_dict()}, event="task.confirmed_unverified")
            return self.store.get(mission_id) or {}
        task.status = TaskStatus.RUNNING
        graph.complete(step_id, dict(result or {}), [proof.as_dict()])
        self.store.save(mission_id, graph, status="running", checkpoint={"task": step_id, "evidence": proof.as_dict()}, event="task.confirmed")
        return self.resume(mission_id, executor=executor, on_step=on_step)

    def waiting_preflight(self) -> list[dict]:
        rows = []
        for row in self.store.recent(100):
            if row.get("status") != "waiting_user":
                continue
            record = self.store.get(row["id"])
            if (record.get("checkpoint") or {}).get("confirmation_mode") == "preflight":
                rows.append(record)
        return rows

    def mission_for_action(self, action_id: str) -> tuple[str, str] | None:
        for row in self.store.recent(100):
            record = self.store.get(row["id"])
            checkpoint = (record or {}).get("checkpoint") or {}
            if checkpoint.get("confirmation_mode") == "executor_pending" and str(checkpoint.get("action_id")) == str(action_id):
                return str(row["id"]), str(checkpoint.get("task"))
        return None

    def resume_preflight(self, mission_id: str, step_id: str, *, executor: Callable[[str, dict], dict], on_step=None) -> dict:
        record = self.store.get(str(mission_id))
        if not record or record.get("status") != "waiting_user":
            raise ValueError("mission is not awaiting preflight confirmation")
        checkpoint = record.get("checkpoint") or {}
        if checkpoint.get("confirmation_mode") != "preflight" or checkpoint.get("task") != step_id:
            raise ValueError("preflight binding mismatch")
        return self.resume(mission_id, executor=executor, confirmed_steps={step_id}, on_step=on_step)

    def resume(self, mission_id: str, *, executor: Callable[[str, dict], dict], confirmed_steps: set[str] | None = None, on_step=None) -> dict:
        record = self.store.get(str(mission_id))
        if not record:
            raise KeyError(mission_id)
        plan = record.get("plan") or {}
        if not plan.get("steps"):
            raise ValueError("mission plan unavailable")
        parsed = MissionPlan.from_dict(plan)
        if self.catalog is not None:
            from .planner import PlanValidator
            parsed = PlanValidator(self.catalog).validate(parsed)
        specs = [self._spec_from_plan_step(s) for s in parsed.steps]
        names = {name for spec in specs for name in (spec.action, spec.precondition_action, spec.rollback_action, *spec.fallbacks) if name}
        for name in names:
            self.register_action(name, lambda _action=name, **kwargs: executor(_action, kwargs))
        return self.run(parsed.objective, specs, confirmed_steps=confirmed_steps, mission_id=str(mission_id), existing_graph=TaskGraph.from_dict(record["graph"]), on_step=on_step, plan_payload=parsed.as_dict())

    @staticmethod
    def _spec_from_plan_step(step: PlannedStep) -> StepSpec:
        return StepSpec(step.id, step.label, step.action, dict(step.arguments), dict(step.expected), frozenset(step.dependencies), step.timeout, step.max_attempts, step.risk, precondition_action=(step.precondition or {}).get("action") if step.precondition else None, precondition_arguments=(step.precondition or {}).get("arguments") if step.precondition else None, precondition_expected=(step.precondition or {}).get("expected") if step.precondition else None, fallbacks=step.fallbacks, rollback_action=(step.rollback or {}).get("action") if step.rollback else None, rollback_arguments=(step.rollback or {}).get("arguments") if step.rollback else None)

    def cancel_all(self) -> int:
        with self._token_lock:
            tokens = tuple(self._tokens)
        for token in tokens:
            token.cancel()
        return len(tokens)

    def cancel(self, mission_id: str) -> dict:
        with self._token_lock:
            token = self._tokens_by_mission.get(str(mission_id))
            if token is not None:
                token.cancel()
        record = self.store.get(str(mission_id))
        if not record:
            raise KeyError(mission_id)
        graph = TaskGraph.from_dict(record["graph"])
        graph.cancel()
        self.store.save(str(mission_id), graph, status="cancelled", event="mission.cancelled")
        return self.store.get(str(mission_id)) or {}

    def recover_interrupted(self) -> int:
        """Mark RUNNING missions uncertain; never resumes their side effects."""
        recovered = 0
        for row in self.store.recent(100):
            if row.get("status") != "running":
                continue
            record = self.store.get(row["id"])
            graph = TaskGraph.from_dict(record["graph"])
            changed = False
            for task in graph.tasks.values():
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.NEEDS_VERIFICATION
                    task.error = "needs_verification after restart"
                    changed = True
            if changed:
                self.store.save(row["id"], graph, status="needs_verification", event="mission.recovered_uncertain")
                recovered += 1
        return recovered

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
