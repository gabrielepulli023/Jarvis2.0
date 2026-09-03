import os
import shutil
from pathlib import Path


def data_directory():
    override = os.environ.get("JARVIS_DATA_DIR")
    if override:
        root = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        root = Path(base) / "JARVIS"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".jarvis-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        root = Path(__file__).resolve().parent / "data"
        root.mkdir(parents=True, exist_ok=True)
    return root


def data_path(name, migrate=True):
    target = data_directory() / name
    legacy = Path(__file__).resolve().parent / name
    if migrate and not target.exists() and legacy.exists() and legacy.resolve() != target.resolve():
        try:
            shutil.copy2(legacy, target)
        except OSError:
            pass
    return target
