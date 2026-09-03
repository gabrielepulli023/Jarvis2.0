import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from app_paths import data_path
from audit_log import record


ROOT = data_path("projects")
VERSIONS = data_path("project_versions")
MANIFEST = data_path("jarvis_projects.json")
MAX_FILES = 40
MAX_TOTAL_CHARS = 800_000


def _safe_name(value):
    name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", str(value or "")).strip(" .")[:80]
    if not name:
        raise ValueError("Nome progetto non valido")
    return name


def _safe_relative_path(value):
    raw = str(value or "").replace("\\", "/").strip().lstrip("/")
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Percorso file non valido: {value}")
    return path


def _load_manifest():
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_manifest(data):
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_project(name, project_type, description, files, overwrite=False):
    """Crea o aggiorna un progetto multi-file senza eseguire il codice generato."""
    safe_name = _safe_name(name)
    rows = list(files or [])
    if not rows or len(rows) > MAX_FILES:
        return {"successo": False, "messaggio": f"Servono da 1 a {MAX_FILES} file per progetto."}
    total = sum(len(str(row.get("content", ""))) for row in rows if isinstance(row, dict))
    if total > MAX_TOTAL_CHARS:
        return {"successo": False, "messaggio": "Il progetto supera la dimensione massima consentita."}

    project_root = (ROOT / safe_name).resolve()
    if project_root.exists() and not overwrite:
        return {
            "successo": False,
            "messaggio": f"Il progetto {safe_name} esiste già. Per aggiornarlo imposta overwrite su true.",
            "percorso": str(project_root),
        }
    ROOT.mkdir(parents=True, exist_ok=True)
    if project_root.exists() and overwrite:
        version_root = VERSIONS / safe_name / str(int(time.time() * 1000))
        version_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(project_root, version_root)
    project_root.mkdir(parents=True, exist_ok=True)

    written = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        relative = _safe_relative_path(row.get("path"))
        target = (project_root / relative).resolve()
        if project_root != target and project_root not in target.parents:
            raise ValueError("Tentativo di uscire dalla cartella del progetto")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(row.get("content", "")), encoding="utf-8")
        written.append(str(relative).replace("\\", "/"))

    manifest = _load_manifest()
    manifest[safe_name.lower()] = {
        "name": safe_name,
        "type": str(project_type or "software")[:80],
        "description": str(description or "")[:1000],
        "path": str(project_root),
        "files": written,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_manifest(manifest)
    record("project_created", name=safe_name, project_type=project_type, files=written)
    return {
        "successo": True,
        "messaggio": f"Progetto {safe_name} creato con {len(written)} file.",
        "dati": manifest[safe_name.lower()],
    }


def list_projects():
    return list(_load_manifest().values())


def restore_project_version(name):
    safe_name = _safe_name(name)
    versions_root = VERSIONS / safe_name
    versions = sorted((path for path in versions_root.iterdir() if path.is_dir()), reverse=True) if versions_root.is_dir() else []
    if not versions:
        return {"successo": False, "messaggio": "Nessuna versione precedente disponibile."}
    target = ROOT / safe_name
    current_backup = versions_root / f"rollback_{int(time.time() * 1000)}"
    if target.exists():
        shutil.copytree(target, current_backup)
        shutil.rmtree(target)
    shutil.copytree(versions[0], target)
    return {"successo": True, "messaggio": f"Progetto {safe_name} ripristinato alla versione precedente.", "percorso": str(target)}
