"""Manual ElevenLabs smoke test; never collected by the automated test suite."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from app_paths import data_path
from jarvis_voice.elevenlabs import ElevenLabsTTSProvider


def main() -> int:
    load_dotenv()
    provider = ElevenLabsTTSProvider(data_path("tts_cache"))
    target = Path(data_path("acceptance")) / "elevenlabs_voice_test.mp3"
    try:
        provider.synthesize("Ciao. Sono Jarvis. Tutti i sistemi vocali sono operativi.", target)
    except Exception as exc:
        print(f"ElevenLabs test fallito: {exc}")
        return 1
    print(f"Audio generato: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
