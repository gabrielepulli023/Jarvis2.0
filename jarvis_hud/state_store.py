from __future__ import annotations

import threading
from copy import deepcopy


class HUDStateStore:
    """Thread-safe HUD projection of real runtime state and events."""

    def __init__(self):
        self._lock = threading.RLock()
        self._state = {
            "core_state": "standby",
            "mode": "DESKTOP",
            "identity": {"status": "loading", "authenticated": False},
            "camera": {"active": False, "privacy": False, "enabled": True},
            "voice": {"state": "unknown"},
            "context": {},
            "capabilities": [],
            "active_tool": "",
        }

    def ingest_snapshot(self, snapshot):
        snapshot = dict(snapshot or {})
        with self._lock:
            runtime = snapshot.get("state", {})
            for key in ("identity", "camera", "vision", "task", "tool"):
                if key in runtime:
                    self._state[key] = deepcopy(runtime[key])
            self._state["voice"] = deepcopy(snapshot.get("voice", self._state["voice"]))
            if snapshot.get("assistant_state"):
                self._state["core_state"] = str(snapshot["assistant_state"])
            self._state["emergency"] = deepcopy(snapshot.get("emergency",self._state.get("emergency",{})))
            self._state["broker"] = deepcopy(snapshot.get("broker",self._state.get("broker",{})))
            self._state["openai"] = deepcopy(snapshot.get("openai", self._state.get("openai", {})))
            incoming_context = snapshot.get("context")
            if isinstance(incoming_context, dict):
                context = dict(self._state.get("context") or {})
                for key, value in incoming_context.items():
                    # Uno snapshot lento non deve cancellare la foreground window
                    # misurata pochi istanti prima dal monitor di sistema.
                    if key == "active_window" and not str(value or "").strip():
                        continue
                    context[key] = deepcopy(value)
                self._state["context"] = context
            self._state["capabilities"] = deepcopy(snapshot.get("capabilities", []))
            self._derive_mode()
            return deepcopy(self._state)

    def ingest_event(self, topic, payload):
        payload = dict(payload or {})
        with self._lock:
            if topic == "state.changed":
                self._state[str(payload.get("key", ""))] = deepcopy(payload.get("value"))
            elif topic == "assistant.state_changed":
                self._state["core_state"] = str(payload.get("state") or "idle")
            elif topic == "voice.partial":
                self._state["partial_transcript"] = str(payload.get("text") or "")
            elif topic == "emergency.stop":
                self._state["emergency"] = {"active":True,"sequence":payload.get("sequence")}
                self._state["core_state"] = "idle"
            elif topic == "emergency.reset":
                self._state["emergency"] = {"active":False}
            elif topic == "camera.started":
                self._state["camera"] = {**payload, "active": True, "privacy": False}
                self._state["core_state"] = "camera"
            elif topic == "camera.stopped":
                previous = dict(self._state.get("camera") or {})
                enabled = bool(payload.get("enabled", previous.get("enabled", True)))
                privacy = bool(payload.get("privacy", not enabled))
                self._state["camera"] = {**previous, **payload, "active": False, "enabled": enabled, "privacy": privacy}
                if self._state.get("core_state") == "camera":
                    self._state["core_state"] = "standby"
            elif topic == "context.active_window":
                context = dict(self._state.get("context") or {})
                context["active_window"] = str(payload.get("active_window") or "")
                self._state["context"] = context
            elif topic.endswith(".started"):
                fallback = topic.removesuffix(".started")
                self._state["active_tool"] = str(
                    payload.get("tool") or payload.get("name") or payload.get("action") or fallback
                )
                self._state["core_state"] = "executing"
            elif topic.endswith(".completed") or topic.endswith(".stopped"):
                self._state["active_tool"] = ""
                self._state["core_state"] = "standby"
            elif topic.endswith(".failed"):
                self._state["core_state"] = "error"
            self._derive_mode()
            return deepcopy(self._state)

    def set_core_state(self, state):
        with self._lock:
            self._state["core_state"] = str(state or "standby").lower()

    def snapshot(self):
        with self._lock:
            return deepcopy(self._state)

    def _derive_mode(self):
        identity = self._state.get("identity") or {}
        camera = self._state.get("camera") or {}
        window = str((self._state.get("context") or {}).get("active_window", "")).lower()
        tool = str((self._state.get("context") or {}).get("last_tool", "")).lower()
        if identity.get("status") == "setup_required":
            mode = "SETUP"
        elif camera.get("active"):
            mode = "CAMERA"
        elif any(x in window for x in ("visual studio", "pycharm", "code", "terminal", "powershell")):
            mode = "CODING"
        elif any(x in window for x in ("trading", "binance", "market", "borsa")):
            mode = "TRADING"
        elif any(x in window for x in ("chrome", "edge", "firefox", "browser")) or tool == "web":
            mode = "BROWSER"
        else:
            mode = "DESKTOP"
        self._state["mode"] = mode
