from __future__ import annotations
import importlib
from pathlib import Path


def probe_wake_model(model_path: Path) -> bool:
    root = Path(model_path)
    return root.is_dir() and (root / "am" / "final.mdl").is_file() and (root / "graph").is_dir()


def probe_audio_input() -> bool:
    devices = importlib.import_module("sounddevice").query_devices()
    return any(int(row.get("max_input_channels", 0)) > 0 for row in devices)


def probe_audio_output() -> bool:
    devices = importlib.import_module("sounddevice").query_devices()
    return any(int(row.get("max_output_channels", 0)) > 0 for row in devices)
