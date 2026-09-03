from __future__ import annotations

import getpass
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "expansion_config.json"


def load():
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def secret(service, username, label):
    import keyring
    value = getpass.getpass(f"{label} (invio per saltare): ").strip()
    if value:
        keyring.set_password(service, username, value)
        print("  salvato in Windows Credential Manager")


def main():
    cfg = load()
    print("\nJARVIS - Configurazione espansioni\n")
    print("Le password/API key non vengono scritte nel JSON: finiscono nel Keyring di Windows.\n")

    current = str(cfg.get("home_assistant_url") or "http://homeassistant.local:8123")
    value = input(f"Home Assistant URL [{current}]: ").strip()
    if value:
        cfg["home_assistant_url"] = value.rstrip("/")
    secret("jarvis.home_assistant", "token", "Home Assistant Long-Lived Access Token")

    secret("jarvis.openai", "api_key", "OpenAI API key per LiteLLM")
    secret("jarvis.anthropic", "api_key", "Anthropic API key per LiteLLM")
    secret("jarvis.gemini", "api_key", "Gemini API key per LiteLLM")
    secret("jarvis.screenpipe", "api_key", "Screenpipe API key (solo se hai abilitato auth)")

    print("\nMCP: i server si aggiungono in expansion_config.json nella sezione mcp_servers.")
    print("ESPHome: i dispositivi si aggiungono nella sezione esphome_devices.")
    save(cfg)
    print(f"\nConfigurazione salvata: {CONFIG}")


if __name__ == "__main__":
    main()
