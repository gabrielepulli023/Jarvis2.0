from __future__ import annotations
import os
import tempfile
from pathlib import Path
from jarvis_terminal import TerminalAgent
from .registry import Capability, SkillManifest, SkillRegistry


def _within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PermissionError(f"path outside skill workspace: {resolved}") from exc
    return resolved


def register_builtin_skills(registry: SkillRegistry, workspace: Path, processes) -> None:
    root = Path(workspace).resolve()
    registry.register(
        SkillManifest(
            "files.read",
            "1.0.0",
            "Read a UTF-8 text file",
            ("read file", "leggi file"),
            frozenset({Capability.READ_FILES}),
            "builtin:read_file",
        ),
        lambda path: {
            "successo": True,
            "messaggio": "File letto.",
            "dati": {"path": str(target := _within(Path(path), root)), "content": target.read_text(encoding="utf-8")},
        },
    )

    def write_file(path: str, content: str):
        target = _within(Path(path), root)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        os.close(handle)
        temp = Path(temp_name)
        try:
            temp.write_text(str(content), encoding="utf-8")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return {
            "successo": True,
            "messaggio": "File scritto e verificato.",
            "dati": {"path": str(target), "size": target.stat().st_size},
        }

    registry.register(
        SkillManifest(
            "files.write",
            "1.0.0",
            "Atomically write a UTF-8 text file",
            ("write file", "scrivi file"),
            frozenset({Capability.WRITE_FILES}),
            "builtin:write_file",
            risk="sensitive",
            verification_strategy="path_size",
        ),
        write_file,
    )
    terminal = TerminalAgent(root, processes)

    def run_process(command: list[str], mission_id: str | None = None, timeout: float = 30, cwd: str | None = None):
        return terminal.execute(command, mission_id, timeout, cwd)

    registry.register(
        SkillManifest(
            "terminal.run",
            "1.0.0",
            "Run an argument-vector subprocess",
            ("run command", "esegui comando"),
            frozenset({Capability.PROCESS_CONTROL}),
            "builtin:run_process",
            risk="sensitive",
            timeout=300,
            retries=0,
            verification_strategy="exit_code",
        ),
        run_process,
    )
