import json
import os
import sys
import threading
from copy import deepcopy
from pathlib import Path
from app_paths import data_path
from jarvis_core.logging import redact

SETTINGS_FILE = data_path("jarvis_settings.json")
_LOCK = threading.RLock()
_CACHE = None
_CACHE_SIGNATURE = None

DEFAULTS = {
    "voice_name": "it-IT-ElsaNeural",
    "voice_rate": -4,
    "voice_pitch": -2,
    "voice_volume": 0,
    "mic_device": None,
    "output_device": None,
    "mic_sensitivity": 100,
    "vad_mode": 3,
    "silence_ms": 420,
    "performance_mode": True,
    "operational_router_always": True,
    "continuous_listening": True,
    "wake_word_only_standby": False,
    "noise_reduction": True,
    "auto_start": False,
    "debug_mode": True,
    "theme": "Olografico Blu",
    "animations_enabled": True,
    "market_refresh_seconds": 60,
    "market_interval": "5m",
    "ai_model": "gpt-5.6-luna",
    "ai_provider": "auto",
    "claude_model": "claude-haiku-4-5-20251001",
    "kimi_model": "kimi-k3",
    "kimi_reasoning_effort": "low",
    "fast_model": "gpt-5-mini",
    "ai_verbosity": "low",
    "ai_memory": True,
    "vision_enabled": True,
    "vision_model": "gpt-5.6-luna",
    "visual_max_steps": 30,
    "agent_auto_repair": True,
    "offline_fallback": True,
    "cognitive_mission_mode": True,
    "critic_max_rounds": 2,
    "critic_min_confidence": 0.65,
    "technical_mode": False,
    "async_engine_enabled": True,
    "smart_cache_enabled": True,
    "privacy_mode": False,
    "biometric_identity_enabled": True,
    "camera_enabled": True,
    "face_camera": 0,
    "face_match_threshold": 0.91,
    "voice_match_threshold": 0.88,
    "wake_speaker_lock": False,
    "startup_face_login": True,
    "ceo_profile_name": "Gabriele",
    "proactive_enabled": True,
    "disk_alert_percent": 90,
    "compact_mode": False,
    "market_watchlist": None,
    "startup_stage_timeout_seconds": 20.0,
    "local_streaming_stt": True,
    "prefer_local_stt": False,
    "stt_language": "it",
    "stt_language_lock": True,
    "application_aliases": {},
    "site_aliases": {},
    "vad_provider": "silero",
    "silero_enabled": True,
    "silero_threshold": 0.55,
    "silero_release_threshold": 0.35,
    "silero_min_speech_ms": 180,
    "silero_min_silence_ms": 540,
    "silero_grace_ms": 300,
    "silero_preroll_ms": 300,
    # External agent integrations are optional, lazy-loaded and isolated from
    # the stable native JARVIS paths.
    "external_integrations_enabled": True,
    "browser_use_enabled": True,
    "browser_use_model": "",
    "browser_use_max_steps": 25,
    "ufo_enabled": True,
    "ufo_base_url": "http://127.0.0.1:5000",
    "ufo_client_id": "jarvis_windows",
    "ufo_poll_seconds": 2.0,
    "ufo_timeout_seconds": 180.0,
    "langgraph_enabled": True,
    "mem0_enabled": False,
    "mem0_user_id": "jarvis_owner",
    "pipecat_enabled": False,
    "ui_tars_enabled": True,
    "ui_tars_timeout_seconds": 180.0,
    "screenpipe_enabled": True,
    "screenpipe_autostart": True,
    "screenpipe_url": "http://127.0.0.1:3030",
    "screenpipe_startup_timeout": 30.0,
    "llama_cpp_enabled": True,
    "llama_cpp_autostart": True,
    "llama_cpp_executable": "",
    "llama_cpp_model": "bartowski/Qwen2.5-3B-Instruct-GGUF:Q4_K_M",
    "llama_cpp_host": "127.0.0.1",
    "llama_cpp_port": 8080,
    "llama_cpp_startup_timeout": 90.0,
    "openhands_enabled": True,
    "openhands_autostart": True,
    "openhands_url": "http://127.0.0.1:3000",
    "openhands_wsl_distro": "Ubuntu",
    "openhands_startup_timeout": 60.0,
}


def _normalize(data):
    """Keep persisted settings type-safe while preserving unknown extensions."""
    normalized = dict(data)
    for key, default in DEFAULTS.items():
        if key not in normalized or default is None:
            continue
        value = normalized[key]
        if isinstance(default, bool):
            if isinstance(value, bool):
                continue
            if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
                normalized[key] = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                normalized[key] = default
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                normalized[key] = default
        elif isinstance(default, float):
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError):
                normalized[key] = default
        elif not isinstance(value, type(default)):
            normalized[key] = default
    return normalized


def _load_raw():
    global _CACHE, _CACHE_SIGNATURE
    try:
        stat = SETTINGS_FILE.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        signature = None
    if _CACHE is not None and signature == _CACHE_SIGNATURE:
        return deepcopy(_CACHE)
    if signature is None:
        _CACHE = dict(DEFAULTS); _CACHE_SIGNATURE = None
        return deepcopy(_CACHE)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULTS)
        merged.update(data if isinstance(data, dict) else {})
        merged = _normalize(merged)
        _CACHE, _CACHE_SIGNATURE = merged, signature
        return deepcopy(merged)
    except Exception:
        _CACHE, _CACHE_SIGNATURE = dict(DEFAULTS), signature
        return deepcopy(_CACHE)


def _save_raw(data):
    global _CACHE, _CACHE_SIGNATURE
    data = _normalize(data)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(SETTINGS_FILE.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)
    stat = SETTINGS_FILE.stat()
    _CACHE, _CACHE_SIGNATURE = deepcopy(data), (stat.st_mtime_ns, stat.st_size)
    return deepcopy(data)


def load_settings():
    with _LOCK:
        return _load_raw()


def get_setting(key, default=None):
    with _LOCK:
        data = _load_raw()
        return data.get(key, DEFAULTS.get(key, default))


def set_setting(key, value):
    with _LOCK:
        data = _load_raw()
        data[key] = value
        normalized = _save_raw(data)
        return normalized.get(key)


def update_settings(values):
    with _LOCK:
        data = _load_raw()
        data.update(values)
        return _save_raw(data)


def set_windows_autostart(enabled, script_path=None):
    """Attiva/disattiva JARVIS nell'avvio dell'utente Windows."""
    if os.name != "nt":
        return False, "Avvio automatico disponibile solo su Windows."

    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        python_exe = Path(sys.executable).resolve()
        script = Path(script_path or (Path(__file__).resolve().parent / "main.py")).resolve()
        command = f'"{python_exe}" "{script}"'

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, "JarvisAssistant", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "JarvisAssistant")
                except FileNotFoundError:
                    pass

        set_setting("auto_start", bool(enabled))
        return True, "Avvio automatico aggiornato."
    except Exception as exc:
        return False, redact(f"Impossibile aggiornare l'avvio automatico: {exc}")
