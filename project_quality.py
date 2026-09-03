import json
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

from app_paths import data_path
from jarvis_core.logging import redact


MANIFEST = data_path("jarvis_projects.json")


def _project(name):
    try:
        rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
        item = rows.get(str(name).lower())
        return Path(item["path"]) if item else None
    except Exception:
        return None


def inspect_project(name):
    root = _project(name)
    if not root or not root.is_dir():
        return {"successo": False, "messaggio": "Progetto non trovato."}
    issues, files = [], []
    for path in root.rglob("*"):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        files.append(str(path.relative_to(root)))
        if path.suffix.lower() == ".py":
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except Exception as exc:
                issues.append(redact(f"{path.name}: {exc}"))
        elif path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(redact(f"{path.name}: JSON non valido: {exc}"))
    return {"successo": not issues, "messaggio": "Progetto valido." if not issues else "; ".join(issues[:20]), "dati": {"path": str(root), "files": files, "issues": issues}}


def test_project(name, timeout=90, confermato=False):
    root = _project(name)
    if not root or not root.is_dir():
        return {"successo": False, "messaggio": "Progetto non trovato."}
    if not confermato:
        return {"successo": False, "richiede_conferma": True, "messaggio": "L'esecuzione dei test richiede conferma."}
    candidates = [
        Path.cwd() / ".python" / "cpython-3.12.13-windows-x86_64-none" / "python.exe",
        Path(sys.executable).resolve().parent.parent.parent / ".python" / "cpython-3.12.13-windows-x86_64-none" / "python.exe",
    ]
    python_exe = next((str(path) for path in candidates if path.exists()), None) or shutil.which("python")
    if not python_exe:
        return {"successo": False, "messaggio": "Runtime Python isolato non disponibile."}
    command = [python_exe, "-I", "-m", "unittest", "discover", "-v"]
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis_project_sandbox_") as sandbox:
            sandbox_root = Path(sandbox) / "project"
            shutil.copytree(root, sandbox_root)
            result = subprocess.run(command, cwd=sandbox_root, capture_output=True, text=True, timeout=max(5, min(int(timeout), 300)), shell=False)
        output = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        return {"successo": result.returncode == 0, "messaggio": output or "Test completati.", "codice": result.returncode, "sandbox": True}
    except subprocess.TimeoutExpired:
        return {"successo": False, "messaggio": "Test interrotti per timeout."}
