from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from settings_store import get_setting




def _read_secret(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

def _setting_bool(name: str, default: bool) -> bool:
    return bool(get_setting(name, default))


def _setting_int(name: str, default: int) -> int:
    try:
        return int(get_setting(name, default))
    except (TypeError, ValueError):
        return int(default)


def _setting_float(name: str, default: float) -> float:
    try:
        return float(get_setting(name, default))
    except (TypeError, ValueError):
        return float(default)


@dataclass(slots=True)
class IntegrationConfig:
    project_root: Path
    enabled: bool
    browser_use_enabled: bool
    ufo_enabled: bool
    langgraph_enabled: bool
    mem0_enabled: bool
    pipecat_enabled: bool
    ui_tars_enabled: bool
    browser_model: str
    browser_max_steps: int
    ufo_base_url: str
    ufo_client_id: str
    ufo_api_key: str
    ufo_poll_seconds: float
    ufo_timeout_seconds: float
    mem0_user_id: str
    ui_tars_timeout_seconds: float

    @classmethod
    def load(cls, project_root: Path | None = None) -> "IntegrationConfig":
        root_override = os.getenv("JARVIS_INTEGRATIONS_ROOT")
        if root_override:
            root = Path(root_override).expanduser().resolve()
        elif getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            root = Path(project_root or Path(__file__).resolve().parent.parent).resolve()
        return cls(
            project_root=root,
            enabled=_setting_bool("external_integrations_enabled", True),
            browser_use_enabled=_setting_bool("browser_use_enabled", True),
            ufo_enabled=_setting_bool("ufo_enabled", True),
            langgraph_enabled=_setting_bool("langgraph_enabled", True),
            mem0_enabled=_setting_bool("mem0_enabled", False),
            pipecat_enabled=_setting_bool("pipecat_enabled", False),
            ui_tars_enabled=_setting_bool("ui_tars_enabled", True),
            browser_model=str(get_setting("browser_use_model", "") or "").strip(),
            browser_max_steps=max(1, min(100, _setting_int("browser_use_max_steps", 25))),
            ufo_base_url=str(get_setting("ufo_base_url", "http://127.0.0.1:5000") or "http://127.0.0.1:5000").rstrip("/"),
            ufo_client_id=str(get_setting("ufo_client_id", "jarvis_windows") or "jarvis_windows").strip(),
            ufo_api_key=(
                str(os.getenv("JARVIS_UFO_API_KEY") or "").strip()
                or _read_secret(root / "external_integrations" / "UFO" / ".jarvis_ufo_server_key")
            ),
            ufo_poll_seconds=max(1.0, min(10.0, _setting_float("ufo_poll_seconds", 2.0))),
            ufo_timeout_seconds=max(10.0, min(1800.0, _setting_float("ufo_timeout_seconds", 180.0))),
            mem0_user_id=str(get_setting("mem0_user_id", "jarvis_owner") or "jarvis_owner").strip(),
            ui_tars_timeout_seconds=max(10.0, min(1800.0, _setting_float("ui_tars_timeout_seconds", 180.0))),
        )

    @property
    def ui_tars_bridge(self) -> Path:
        return self.project_root / "external_integrations" / "ui_tars" / "ui_tars_bridge.mjs"

    @property
    def ui_tars_package_dir(self) -> Path:
        return self.project_root / "external_integrations" / "ui_tars"
