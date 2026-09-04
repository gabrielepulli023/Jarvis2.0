from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    WAITING_USER = "waiting_user"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Task:
    id: str
    label: str
    dependencies: set[str] = field(default_factory=set)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    result: dict | None = None
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        row = asdict(self)
        row["dependencies"] = sorted(self.dependencies)
        row["status"] = self.status.value
        return row


class TaskGraph:
    def __init__(self, tasks: list[Task] | None = None):
        self.tasks = {task.id: task for task in (tasks or [])}
        self.cancelled = False
        self.validate()

    @classmethod
    def from_dict(cls, value: dict) -> "TaskGraph":
        rows = value.get("tasks", []) if isinstance(value, dict) else []
        tasks = []
        for row in rows[:32]:
            task = Task(str(row["id"]), str(row.get("label", row["id"]))[:200], set(row.get("dependencies", [])))
            task.status = TaskStatus(str(row.get("status", "pending")))
            task.attempts = max(0, int(row.get("attempts", 0)))
            task.max_attempts = max(1, min(5, int(row.get("max_attempts", 3))))
            task.result = dict(row.get("result") or {})
            task.evidence = list(row.get("evidence") or [])[:8]
            task.error = str(row.get("error"))[:500] if row.get("error") else None
            tasks.append(task)
        graph = cls(tasks)
        graph.cancelled = bool(value.get("cancelled", False)) if isinstance(value, dict) else False
        return graph

    def add(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"duplicate task id: {task.id}")
        self.tasks[task.id] = task
        self.validate()

    def validate(self) -> None:
        for task in self.tasks.values():
            missing = task.dependencies - set(self.tasks)
            if missing:
                raise ValueError(f"task {task.id} has missing dependencies: {sorted(missing)}")
        visiting = set()
        visited = set()

        def walk(task_id):
            if task_id in visiting:
                raise ValueError("task graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self.tasks[task_id].dependencies:
                walk(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self.tasks:
            walk(task_id)

    def refresh(self) -> None:
        for task in self.tasks.values():
            if task.status not in {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.BLOCKED}:
                continue
            deps = [self.tasks[x].status for x in task.dependencies]
            if any(
                x in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.SKIPPED} for x in deps
            ):
                task.status = TaskStatus.BLOCKED
            elif all(x == TaskStatus.COMPLETED for x in deps):
                task.status = TaskStatus.READY

    def ready(self) -> list[Task]:
        self.refresh()
        return [x for x in self.tasks.values() if x.status in {TaskStatus.READY, TaskStatus.RETRY}]

    def start(self, task_id: str) -> Task:
        self.refresh()
        task = self.tasks[task_id]
        if self.cancelled:
            raise RuntimeError("mission is cancelled")
        if task.status not in {TaskStatus.READY, TaskStatus.RETRY}:
            raise RuntimeError(f"task is not ready: {task.status}")
        task.status = TaskStatus.RUNNING
        task.attempts += 1
        return task

    def complete(self, task_id: str, result: dict, evidence: list[dict]) -> None:
        task = self.tasks[task_id]
        if task.status != TaskStatus.RUNNING:
            raise RuntimeError("task is not running")
        if not evidence:
            raise ValueError("completed task requires evidence")
        task.result = dict(result)
        task.evidence = list(evidence)
        task.error = None
        task.status = TaskStatus.COMPLETED
        self.refresh()

    def fail(self, task_id: str, error: str) -> None:
        task = self.tasks[task_id]
        if task.status != TaskStatus.RUNNING:
            raise RuntimeError("task is not running")
        task.error = str(error)
        task.status = TaskStatus.RETRY if task.attempts < task.max_attempts else TaskStatus.FAILED
        self.refresh()

    def wait_for_user(self, task_id: str, reason: str) -> None:
        task = self.tasks[task_id]
        if task.status not in {TaskStatus.READY, TaskStatus.RETRY, TaskStatus.RUNNING}:
            raise RuntimeError("task is not ready")
        task.error = str(reason)
        task.status = TaskStatus.WAITING_USER

    def skip(self, task_id: str, reason: str) -> None:
        task = self.tasks[task_id]
        task.error = str(reason)
        task.status = TaskStatus.SKIPPED
        self.refresh()

    def cancel(self) -> None:
        self.cancelled = True
        for task in self.tasks.values():
            if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                task.status = TaskStatus.CANCELLED

    def progress(self) -> float:
        return (
            1.0
            if not self.tasks
            else sum(x.status == TaskStatus.COMPLETED for x in self.tasks.values()) / len(self.tasks)
        )

    def as_dict(self) -> dict:
        return {
            "cancelled": self.cancelled,
            "progress": self.progress(),
            "tasks": [x.as_dict() for x in self.tasks.values()],
        }
