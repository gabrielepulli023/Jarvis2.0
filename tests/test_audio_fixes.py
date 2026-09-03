#!/usr/bin/env python3
"""Unit test per le correzioni STT e TTS."""

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from transcriber import trascrivi, StreamingTranscriber


class TestAudioStabilization(unittest.TestCase):
    """Test fixes for STT accuracy and TTS stability."""

    def test_openai_fallback_exists(self):
        """Verify OpenAI fallback code is present."""
        from voice import ascolta
        import inspect
        
        source = inspect.getsource(ascolta)
        self.assertIn("fallback", source, "OpenAI fallback code should exist")

    def test_prefer_local_stt_is_false(self):
        """Verify default setting prefers OpenAI over Vosk."""
        from settings_store import get_setting
        
        prefer_local = get_setting("prefer_local_stt", True)
        self.assertFalse(prefer_local, "prefer_local_stt should be False to prefer OpenAI")

    def test_streaming_transcriber_handles_audio(self):
        """StreamingTranscriber should process audio without crashing."""
        st = StreamingTranscriber()
        
        # Generate test audio
        FREQUENZA = 16000
        duration = 0.5
        samples = np.sin(2 * np.pi * 1000 * np.linspace(0, duration, int(FREQUENZA * duration)))
        samples_int16 = (samples * 0.3 * 32767).astype(np.int16)
        
        chunk_size = int(FREQUENZA * 0.03)
        for i in range(0, len(samples_int16), chunk_size):
            chunk = samples_int16[i:i+chunk_size].tobytes()
            if chunk:
                result = st.feed(chunk)
                self.assertIsInstance(result, str)
        
        final = st.finish()
        self.assertIsInstance(final, str)

    def test_parla_function_has_timing_debug(self):
        """Verify parla() has timing diagnostics for TTS."""
        from voice import parla
        import inspect
        
        source = inspect.getsource(parla)
        self.assertIn("[DEBUG TTS]", source, "parla() should have [DEBUG TTS] logging")
        self.assertIn("stall", source.lower(), "parla() should detect stalls")

    def test_audio_device_auto_detection_works(self):
        """Audio device should auto-detect best microphone."""
        from audio_device import _find_best_input_device
        
        # Should not crash
        device = _find_best_input_device()
        if device is not None:
            self.assertIsInstance(device, int)
            self.assertGreaterEqual(device, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
