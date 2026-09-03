from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
import zipfile
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from jarvis_core.errors import PermissionError
from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class FileOperation:
    action: str
    source: str | None = None
    target: str | None = None
    content: str | None = None


@dataclass(frozen=True, slots=True)
class FileOperationPlan:
    id: str
    operations: tuple[FileOperation, ...]
    destructive: bool
    confirmation_required: bool
    summary: dict[str, int]


@dataclass(frozen=True, slots=True)
class FileOperationResult:
    success: bool
    plan_id: str
    completed: int
    rolled_back: bool
    errors: tuple[str, ...] = ()


class FileAgent:
    """Transactional file operations constrained to explicitly allowed roots."""

    ACTIONS = {"copy", "move", "rename", "delete", "mkdir", "write", "append"}

    def __init__(self, allowed_roots: list[Path], transaction_root: Path, *, massive_threshold: int = 20):
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        self.transaction_root = Path(transaction_root).resolve()
        self.transaction_root.mkdir(parents=True, exist_ok=True)
        self.massive_threshold = max(2, int(massive_threshold))
        self._plans: OrderedDict[str, FileOperationPlan] = OrderedDict()
        self._lock = threading.RLock()

    def plan(self, operations: list[FileOperation]) -> FileOperationPlan:
        if not operations:
            raise ValueError("Il piano file è vuoto")
        summary: dict[str, int] = {}
        validated = []
        for operation in operations:
            if operation.action not in self.ACTIONS:
                raise ValueError(f"Operazione non supportata: {operation.action}")
            if operation.source:
                self._safe(operation.source)
            if operation.target:
                self._safe(operation.target)
            if operation.action in {"copy", "move", "rename"} and (not operation.source or not operation.target):
                raise ValueError(f"{operation.action} richiede source e target")
            if operation.action in {"delete"} and not operation.source:
                raise ValueError("delete richiede source")
            if operation.action in {"mkdir", "write", "append"} and not operation.target:
                raise ValueError(f"{operation.action} richiede target")
            summary[operation.action] = summary.get(operation.action, 0) + 1
            validated.append(operation)
        destructive = any(item.action in {"delete", "move", "rename"} for item in validated)
        plan = FileOperationPlan(
            str(uuid.uuid4()),
            tuple(validated),
            destructive,
            destructive or len(validated) >= self.massive_threshold,
            summary,
        )
        with self._lock:
            self._plans[plan.id] = plan
            while len(self._plans) > 128:
                self._plans.popitem(last=False)
        return plan

    def execute_plan(self, plan_id: str, *, confirmed: bool = False, dry_run: bool = False) -> FileOperationResult:
        with self._lock:
            plan = self._plans.get(str(plan_id))
        if plan is None:
            return FileOperationResult(False, str(plan_id), 0, False, ("Piano inesistente o scaduto",))
        return self.execute(plan, confirmed=confirmed, dry_run=dry_run)

    def execute(
        self, plan: FileOperationPlan, *, confirmed: bool = False, dry_run: bool = False
    ) -> FileOperationResult:
        if plan.confirmation_required and not confirmed:
            return FileOperationResult(False, plan.id, 0, False, ("Conferma richiesta",))
        if dry_run:
            return FileOperationResult(True, plan.id, 0, False)
        journal_dir = self.transaction_root / plan.id
        journal_dir.mkdir(parents=True, exist_ok=False)
        undo: list[dict[str, Any]] = []
        completed = 0
        try:
            for index, operation in enumerate(plan.operations):
                undo.append(self._execute_one(operation, journal_dir, index))
                completed += 1
                self._write_journal(journal_dir, plan, undo, "running")
            self._write_journal(journal_dir, plan, undo, "completed")
            return FileOperationResult(True, plan.id, completed, False)
        except (OSError, ValueError) as exc:
            errors = [redact(f"{type(exc).__name__}: {exc}")]
            rolled_back = self._rollback_entries(reversed(undo), errors)
            self._write_journal(journal_dir, plan, undo, "rolled_back" if rolled_back else "rollback_failed", errors)
            return FileOperationResult(False, plan.id, completed, rolled_back, tuple(errors))

    def rollback(self, plan_id: str) -> FileOperationResult:
        journal_dir = self.transaction_root / str(plan_id)
        data = json.loads((journal_dir / "journal.json").read_text(encoding="utf-8"))
        errors: list[str] = []
        success = self._rollback_entries(reversed(data.get("undo", [])), errors)
        data["status"] = "rolled_back" if success else "rollback_failed"
        data["errors"] = errors
        (journal_dir / "journal.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return FileOperationResult(success, str(plan_id), len(data.get("undo", [])), success, tuple(errors))

    def checksum(self, path: str | Path) -> str:
        target = self._safe(path)
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def metadata(self, path: str | Path) -> dict:
        target = self._safe(path)
        stat = target.stat()
        return {
            "path": str(target),
            "name": target.name,
            "extension": target.suffix,
            "is_file": target.is_file(),
            "is_dir": target.is_dir(),
            "size": stat.st_size,
            "created_at": stat.st_ctime,
            "modified_at": stat.st_mtime,
            "mode": stat.st_mode,
        }

    def compare(self, left: str | Path, right: str | Path) -> dict:
        first = self._safe(left)
        second = self._safe(right)
        if not first.is_file() or not second.is_file():
            raise ValueError("Il confronto richiede due file")
        left_hash = self.checksum(first)
        right_hash = self.checksum(second)
        return {
            "equal": left_hash == right_hash,
            "left": {"path": str(first), "size": first.stat().st_size, "sha256": left_hash},
            "right": {"path": str(second), "size": second.stat().st_size, "sha256": right_hash},
        }

    def archive(self, sources: list[str], target: str) -> dict:
        paths = [self._safe(value) for value in sources]
        destination = self._safe(target)
        if not paths:
            raise ValueError("Nessun file da comprimere")
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for source in paths:
                    if source.is_dir():
                        for item in source.rglob("*"):
                            if item.is_file():
                                archive.write(item, item.relative_to(source.parent))
                    else:
                        archive.write(source, source.name)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            "success": True,
            "message": "Archivio creato.",
            "data": {
                "path": str(destination),
                "sources": len(paths),
                "size": destination.stat().st_size,
                "sha256": self.checksum(destination),
            },
        }

    def inspect_archive(self, source: str) -> dict:
        archive_path = self._safe(source)
        with zipfile.ZipFile(archive_path, "r") as archive:
            rows = [
                {"name": item.filename, "size": item.file_size, "compressed": item.compress_size}
                for item in archive.infolist()[:10000]
            ]
        return {"path": str(archive_path), "entries": rows, "count": len(rows)}

    def extract(self, source: str, target: str) -> dict:
        archive_path = self._safe(source)
        destination = self._safe(target)
        if destination.exists():
            raise FileExistsError("La destinazione deve essere nuova per consentire rollback sicuro")
        destination.mkdir(parents=True)
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                members = archive.infolist()
                for member in members:
                    output = (destination / member.filename).resolve()
                    if output != destination and not output.is_relative_to(destination):
                        raise ValueError("Archivio contiene un percorso non sicuro")
                archive.extractall(destination)
        except Exception:
            self._remove(destination)
            raise
        return {
            "success": True,
            "message": "Archivio estratto.",
            "data": {"path": str(destination), "entries": len(members)},
        }

    def _execute_one(self, operation: FileOperation, journal_dir: Path, index: int) -> dict:
        source = self._safe(operation.source) if operation.source else None
        target = self._safe(operation.target) if operation.target else None
        backup = journal_dir / f"backup_{index}"
        if operation.action == "mkdir":
            assert target is not None
            target.mkdir(parents=True, exist_ok=False)
            return {"action": "remove", "path": str(target)}
        if operation.action in {"write", "append"}:
            assert target is not None
            existed = target.exists()
            if existed:
                self._backup(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a" if operation.action == "append" else "w", encoding="utf-8") as stream:
                stream.write(operation.content or "")
            return {
                "action": "restore" if existed else "remove",
                "path": str(target),
                "backup": str(backup) if existed else None,
            }
        if operation.action == "copy":
            assert source is not None and target is not None
            if target.exists():
                self._backup(target, backup)
            self._copy(source, target)
            return {
                "action": "restore" if backup.exists() else "remove",
                "path": str(target),
                "backup": str(backup) if backup.exists() else None,
            }
        if operation.action in {"move", "rename"}:
            assert source is not None and target is not None
            if target.exists():
                raise FileExistsError(str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return {"action": "move", "path": str(target), "target": str(source)}
        if operation.action == "delete":
            assert source is not None
            if not source.exists():
                raise FileNotFoundError(str(source))
            self._backup(source, backup)
            self._remove(source)
            return {"action": "restore", "path": str(source), "backup": str(backup)}
        raise ValueError(operation.action)

    def _safe(self, value: str | Path) -> Path:
        target = Path(value).expanduser().resolve()
        if not any(target == root or root in target.parents for root in self.allowed_roots):
            raise PermissionError(f"Percorso fuori dalle radici consentite: {target}")
        return target

    @staticmethod
    def _copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    def _backup(self, source: Path, backup: Path) -> None:
        self._copy(source, backup)

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _rollback_entries(self, entries, errors: list[str]) -> bool:
        for entry in entries:
            try:
                path = Path(entry["path"])
                if entry["action"] == "remove" and path.exists():
                    self._remove(path)
                elif entry["action"] == "restore":
                    if path.exists():
                        self._remove(path)
                    self._copy(Path(entry["backup"]), path)
                elif entry["action"] == "move":
                    target = Path(entry["target"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(target))
            except OSError as exc:
                errors.append(redact(f"rollback {entry}: {exc}"))
        return not any(value.startswith("rollback ") for value in errors)

    @staticmethod
    def _write_journal(
        root: Path, plan: FileOperationPlan, undo: list[dict], status: str, errors: list[str] | None = None
    ) -> None:
        payload = {
            "plan": {**asdict(plan), "operations": [asdict(item) for item in plan.operations]},
            "undo": undo,
            "status": status,
            "errors": errors or [],
            "updated": time.time(),
        }
        temporary = root / "journal.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, root / "journal.json")
