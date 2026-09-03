from __future__ import annotations
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from jarvis_core.errors import PermissionError


class WorkingDirectoryGuard:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def validate(self, value: str | Path | None) -> Path:
        target = (self.root if value is None else Path(value)).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise PermissionError("Working directory fuori dal workspace")
        if not target.is_dir():
            raise FileNotFoundError(target)
        return target


class ArgumentSanitizer:
    _CONTROL = re.compile(r"[\x00-\x1f\x7f]")

    @classmethod
    def clean(cls, arguments) -> list[str]:
        if not isinstance(arguments, (list, tuple)) or len(arguments) > 128:
            raise ValueError("Argomenti non validi")
        result = []
        for value in arguments:
            text = str(value)
            if len(text) > 8192 or cls._CONTROL.search(text):
                raise ValueError("Argomento non valido")
            result.append(text)
        return result


class CommandValidator:
    GIT_READ = {"status", "diff", "log", "show", "rev-parse", "branch", "ls-files"}
    GIT_WRITE = {"add", "commit", "checkout", "switch", "restore", "merge", "rebase", "tag"}
    PYTHON_MODULES = {"unittest", "pytest", "pip", "ruff", "mypy", "compileall", "venv"}
    WINGET_READ = {"list", "search", "show", "source"}

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def validate(self, command: list[str]) -> list[str]:
        if not command:
            raise ValueError("Comando vuoto")
        executable = str(command[0])
        args = ArgumentSanitizer.clean(command[1:])
        name = Path(executable).name.casefold()
        resolved = (
            Path(executable).resolve()
            if Path(executable).is_absolute()
            else Path(shutil.which(executable) or executable)
        )
        if name in {Path(sys.executable).name.casefold(), "python.exe", "python3.exe"}:
            self._python(args)
        elif name in {"git.exe", "git"}:
            self._subcommand(args, self.GIT_READ | self.GIT_WRITE, "Git")
        elif name in {"winget.exe", "winget"}:
            self._subcommand(args, self.WINGET_READ, "Winget terminale")
        elif name in {"powershell.exe", "pwsh.exe", "powershell", "pwsh"}:
            self._powershell(args)
        elif name in {"cmd.exe", "cmd"}:
            self._cmd(args)
        else:
            raise PermissionError(f"Eseguibile non consentito dal TerminalAgent: {name}")
        return [str(resolved), *args]

    @staticmethod
    def _subcommand(args, allowed, label):
        if not args or args[0].casefold() not in allowed:
            raise PermissionError(f"Sottocomando {label} non consentito")

    def _python(self, args):
        if not args:
            return
        if args[0] in {"--version", "-V"}:
            return
        if args[0] == "-m" and len(args) > 1 and args[1] in self.PYTHON_MODULES:
            return
        if args[0] in {"-c", "-"}:
            raise PermissionError("Codice Python inline non consentito")
        script = Path(args[0]).resolve()
        if script.suffix.casefold() != ".py" or (script != self.root and not script.is_relative_to(self.root)):
            raise PermissionError("Script Python fuori dal workspace")

    def _powershell(self, args):
        lowered = [item.casefold() for item in args]
        if any(item in lowered for item in ("-command", "-c", "-encodedcommand", "-enc")):
            raise PermissionError("PowerShell inline non consentito")
        try:
            index = lowered.index("-file")
        except ValueError as exc:
            raise PermissionError("PowerShell richiede -File") from exc
        script = Path(args[index + 1]).resolve() if index + 1 < len(args) else Path()
        if script.suffix.casefold() != ".ps1" or not script.is_relative_to(self.root):
            raise PermissionError("Script PowerShell fuori dal workspace")

    def _cmd(self, args):
        if len(args) < 2 or args[0].casefold() not in {"/c", "/k"}:
            raise PermissionError("CMD richiede uno script workspace")
        script = Path(args[1]).resolve()
        if script.suffix.casefold() not in {".cmd", ".bat"} or not script.is_relative_to(self.root):
            raise PermissionError("Script CMD fuori dal workspace")


class TerminalAgent:
    def __init__(self, root: Path, processes):
        self.root = Path(root).resolve()
        self.processes = processes
        self.cwd_guard = WorkingDirectoryGuard(self.root)
        self.validator = CommandValidator(self.root)

    def execute(
        self, command: list[str], mission_id: str | None = None, timeout: float = 30, cwd: str | None = None
    ) -> dict:
        validated = self.validator.validate(command)
        working = self.cwd_guard.validate(cwd)
        started = time.monotonic()
        item = self.processes.start(
            validated, mission_id=mission_id, cwd=working, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            stdout, stderr = item.process.communicate(timeout=max(0.1, min(float(timeout), 300)))
        except subprocess.TimeoutExpired:
            self.processes.terminate(item.id)
            return {
                "success": False,
                "message": "Processo scaduto.",
                "data": {
                    "id": item.id,
                    "command": validated,
                    "cwd": str(working),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
        return {
            "success": item.process.returncode == 0,
            "message": "Processo completato." if item.process.returncode == 0 else "Processo fallito.",
            "data": {
                "id": item.id,
                "command": validated,
                "cwd": str(working),
                "exit_code": item.process.returncode,
                "stdout": stdout[-10000:],
                "stderr": stderr[-10000:],
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        }
