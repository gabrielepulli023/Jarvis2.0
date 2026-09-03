import json
import re
import subprocess
import shutil
import sys
from datetime import datetime
from pathlib import Path

from app_paths import data_path
from audit_log import record


ROOT = data_path("scripts")
ROOT.mkdir(parents=True, exist_ok=True)
MANIFEST = data_path("jarvis_scripts.json")
FORBIDDEN = [
    r"(?i)remove-item\s+.*-recurse", r"(?i)format-volume", r"(?i)clear-disk",
    r"(?i)shutdown(?:\.exe)?\b", r"(?i)restart-computer", r"(?i)stop-computer",
    r"(?i)reg\s+(?:delete|add)", r"(?i)invoke-expression", r"(?i)downloadstring",
    r"(?i)rm\s+-rf", r"(?i)os\.system\s*\(", r"(?i)subprocess\.",
]


def _load():
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def inspect_script(code):
    hits = [pattern for pattern in FORBIDDEN if re.search(pattern, str(code))]
    return {"safe": not hits, "blocked_patterns": hits, "lines": len(str(code).splitlines())}


def save_script(name, language, code):
    language = str(language).lower().strip()
    if language not in {"python", "powershell"}:
        raise ValueError("Linguaggio supportato: python o powershell")
    report = inspect_script(code)
    if not report["safe"]:
        return {"successo": False, "messaggio": "Script bloccato dalla verifica di sicurezza.", "analisi": report}
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(name)).strip("_")[:60]
    if not key:
        raise ValueError("Nome script non valido")
    extension = ".py" if language == "python" else ".ps1"
    path = ROOT / (key + extension)
    path.write_text(str(code), encoding="utf-8")
    data = _load(); data[key.lower()] = {"name": key, "language": language, "path": str(path), "created_at": datetime.now().isoformat(timespec="seconds")}; _save(data)
    record("script_saved", name=key, language=language, analysis=report)
    return {"successo": True, "messaggio": f"Script {key} salvato.", "dati": data[key.lower()]}


def list_scripts():
    return list(_load().values())


def run_script(name, arguments=None, timeout=30, confermato=False):
    item = _load().get(str(name).lower())
    if not item:
        return {"successo": False, "messaggio": "Script non trovato."}
    if not confermato:
        return {"successo": False, "richiede_conferma": True, "messaggio": "L'esecuzione dello script richiede conferma."}
    path = Path(item["path"])
    try:
        analysis = inspect_script(path.read_text(encoding="utf-8"))
    except OSError:
        return {"successo": False, "messaggio": "File dello script non leggibile."}
    if not analysis["safe"]:
        record("script_blocked", name=item["name"], analysis=analysis)
        return {"successo": False, "messaggio": "Script modificato o non sicuro: esecuzione bloccata.", "analisi": analysis}
    args = [str(x) for x in (arguments or [])][:20]
    if item["language"] == "python":
        candidates = [
            Path.cwd() / ".python" / "cpython-3.12.13-windows-x86_64-none" / "python.exe",
            Path(sys.executable).resolve().parent.parent.parent / ".python" / "cpython-3.12.13-windows-x86_64-none" / "python.exe",
        ]
        python_exe = next((str(p) for p in candidates if p.exists()), None) or shutil.which("python") or shutil.which("py")
        if not python_exe:
            return {"successo": False, "messaggio": "Runtime Python esterno non disponibile per questo script."}
        command = [python_exe, "-I", str(path)] + args
    else:
        command = ["powershell", "-NoProfile", "-NonInteractive", "-File", str(path)] + args
    record("script_started", name=item["name"], arguments=args)
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=max(1, min(int(timeout), 300)), shell=False)
        payload = {"successo": result.returncode == 0, "messaggio": (result.stdout or result.stderr or "Script completato.")[-4000:], "codice": result.returncode}
    except subprocess.TimeoutExpired:
        payload = {"successo": False, "messaggio": "Script interrotto per timeout."}
    record("script_completed", name=item["name"], result=payload)
    return payload
