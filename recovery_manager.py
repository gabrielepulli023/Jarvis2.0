import json
import shutil
import time
from pathlib import Path

from app_paths import data_path


ROOT = data_path("recovery")
ROOT.mkdir(parents=True, exist_ok=True)
INDEX = data_path("jarvis_recovery.json")


def _load():
    try:
        value = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(value): INDEX.write_text(json.dumps(value[-200:], ensure_ascii=False, indent=2), encoding="utf-8")


def move_to_recovery(path):
    source = Path(path).resolve()
    token = f"{int(time.time() * 1000)}_{source.name}"
    target = ROOT / token
    shutil.move(str(source), str(target))
    data = _load(); data.append({"id": token, "original": str(source), "stored": str(target), "restored": False}); _save(data)
    return token


def restore_last():
    data = _load()
    for item in reversed(data):
        stored = Path(item["stored"]); original = Path(item["original"])
        if not item.get("restored") and stored.exists():
            if original.exists():
                return {"successo": False, "messaggio": "Il percorso originale è già occupato."}
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stored), str(original)); item["restored"] = True; _save(data)
            return {"successo": True, "messaggio": f"Ripristinato {original.name}.", "percorso": str(original)}
    return {"successo": False, "messaggio": "Nessuna eliminazione recuperabile."}
