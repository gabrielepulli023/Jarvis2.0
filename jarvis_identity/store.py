import json
import os
import threading
from pathlib import Path

from app_paths import data_path
from .crypto import protect, unprotect


class BiometricStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_path("identity")
        self.path = self.root / "profiles.json"
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            try:
                value = json.loads(unprotect(self.path.read_bytes()).decode("utf-8"))
                return value if isinstance(value, dict) else {"version": 1, "profiles": {}}
            except (OSError, ValueError):
                return {"version": 1, "profiles": {}}

    def save(self, value):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            temporary.write_bytes(protect(payload))
            os.replace(temporary, self.path)

    def put_template(self, name, kind, templates):
        value = self.load()
        value.setdefault("profiles", {}).setdefault(str(name).strip(), {})[kind] = templates
        self.save(value)

    def put_profile(self, name, face_templates, voice_templates, metadata):
        value = self.load()
        value["version"] = 2
        value.setdefault("profiles", {})[str(name).strip()] = {
            "face": list(face_templates), "voice": list(voice_templates),
            "metadata": dict(metadata or {}),
        }
        self.save(value)

    def profile(self, name):
        value = self.load().get("profiles", {}).get(str(name).strip(), {})
        if not isinstance(value, dict):
            return None
        return {"name": str(name).strip(), "metadata": dict(value.get("metadata") or {}),
                "has_face": bool(value.get("face")), "has_voice": bool(value.get("voice"))}

    def templates(self, kind):
        value = self.load()
        return {name: profile[kind] for name, profile in value.get("profiles", {}).items()
                if isinstance(profile, dict) and profile.get(kind)}

    def delete(self, name):
        value = self.load()
        removed = value.get("profiles", {}).pop(str(name).strip(), None) is not None
        if removed:
            self.save(value)
        return removed
