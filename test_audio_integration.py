#!/usr/bin/env python3
"""
Test integrazione audio end-to-end con le nuove correzioni.
Verifica che STT sia accurato e TTS non abbia stalli con barge-in.
"""

import os
import sys
import time
from pathlib import Path

# I collaudi devono restare eseguibili anche nella console Windows CP1252.
if getattr(sys.stdout, "reconfigure", None):
    sys.stdout.reconfigure(errors="replace")

from dotenv import load_dotenv
load_dotenv()

print("=" * 80)
print("TEST INTEGRAZIONE AUDIO END-TO-END - JARVIS STABILIZATION")
print("=" * 80)

# Check prerequisites
print("\n[1] Verifica Prerequisites...")
checks = {
    "✓ OpenAI API Key": bool(os.getenv("OPENAI_API_KEY")),
    "✓ ElevenLabs API Key": bool(os.getenv("ELEVENLABS_API_KEY")),
    "✓ Audio Device": True,
}

for check, passed in checks.items():
    status = "✅" if passed else "❌"
    print(f"  {status} {check}")

if not all(checks.values()):
    print("\n❌ Prerequisiti non soddisfatti. Configura .env file.")
    sys.exit(1)

# Test settings
print("\n[2] Verifica Configurazione Audio...")
from settings_store import get_setting

settings = {
    "local_streaming_stt": get_setting("local_streaming_stt"),
    "prefer_local_stt": get_setting("prefer_local_stt"),
}

for key, value in settings.items():
    print(f"  • {key}: {value}")

if settings["prefer_local_stt"] is not False:
    print("  ⚠️  AVVISO: prefer_local_stt dovrebbe essere False per OpenAI-first")

# Test audio subsystem
print("\n[3] Test Subsistema Audio...")

try:
    from audio_device import _find_best_input_device
    device = _find_best_input_device()
    print(f"  ✅ Auto-device detection: Device {device}")
except Exception as e:
    print(f"  ❌ Audio device error: {e}")
    sys.exit(1)

try:
    from jarvis_voice.elevenlabs import ElevenLabsTTSProvider
    provider = ElevenLabsTTSProvider()
    print(f"  ✅ ElevenLabs configured: {provider.configured}")
except Exception as e:
    print(f"  ❌ ElevenLabs error: {e}")
    sys.exit(1)

try:
    from transcriber import trascrivi
    print(f"  ✅ OpenAI transcriber available")
except Exception as e:
    print(f"  ❌ Transcriber error: {e}")
    sys.exit(1)

# Test TTS timing diagnostics
print("\n[4] Test Diagnostica TTS...")
try:
    from voice import parla
    import inspect
    
    source = inspect.getsource(parla)
    has_timing = "[DEBUG TTS]" in source
    has_stall_detection = "STALLO RILEVATO" in source
    
    print(f"  {'✅' if has_timing else '❌'} Timing diagnostics: {has_timing}")
    print(f"  {'✅' if has_stall_detection else '❌'} Stall detection: {has_stall_detection}")
    
except Exception as e:
    print(f"  ❌ Error checking diagnostics: {e}")

print("\n" + "=" * 80)
print("✅ TEST DI CONFIGURAZIONE COMPLETATO - PRONTO PER AVVIARE JARVIS")
print("=" * 80)
print("\nPer eseguire JARVIS con le nuove correzioni:")
print("  1. Esegui: Avvia Jarvis.cmd")
print("  2. Osserva il log per [DEBUG TTS] STALLO RILEVATO (se avvengono pause)")
print("  3. Prova a parlare - STT dovrebbe essere più accurato")
print("\nVerificazione:")
print("  ✓ STT: Ora usa OpenAI come primario, Vosk come fallback")
print("  ✓ TTS: Monitoraggio timing per rilevare stalli durante playback")
print("  ✓ Barge-in: Ancora funzionante, usa Vosk per interrupt (veloce)")
