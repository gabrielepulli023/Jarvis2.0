import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_voice.elevenlabs import (
    DEFAULT_MODEL,
    DEFAULT_VOICE_SETTINGS,
    ElevenLabsError,
    ElevenLabsTTSProvider,
    SpeechCostOptimizer,
    format_for_speech,
)


class ElevenLabsTtsTests(unittest.TestCase):
    def test_formatter_removes_code_urls_markdown_and_emoji(self):
        text = "**Risultato** https://example.com `x=1` \U0001f600"
        value = format_for_speech(text)
        self.assertNotIn("http", value)
        self.assertNotIn("x=1", value)
        self.assertNotIn("**", value)

    def test_optimizer_summarizes_long_and_traceback(self):
        optimizer = SpeechCostOptimizer(max_chars=120)
        self.assertLessEqual(len(optimizer.optimize("Una frase molto lunga. " * 40)), 220)
        self.assertIn("errore tecnico", optimizer.optimize("Traceback (most recent call last): ValueError"))

    def test_missing_credentials_fail_closed_without_secret(self):
        from unittest.mock import patch as mock_patch
        with mock_patch("jarvis_voice.elevenlabs.load_dotenv"):
            with mock_patch.dict(os.environ, {}, clear=True):
                provider = ElevenLabsTTSProvider()
                self.assertFalse(provider.configured)
                with self.assertRaisesRegex(ElevenLabsError, "API_KEY"):
                    provider.synthesize("ciao", Path(tempfile.gettempdir()) / "jarvis-test.mp3")

    def test_request_uses_flash_model_and_defaults(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "secret", "ELEVENLABS_VOICE_ID": "voice"}, clear=True):
            provider = ElevenLabsTTSProvider(retries=0)
            self.assertEqual(provider.model, DEFAULT_MODEL)
            self.assertEqual(provider.settings, DEFAULT_VOICE_SETTINGS)
            self.assertNotIn("secret", repr(provider.metrics.snapshot()))

    def test_project_dotenv_is_loaded_for_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = ElevenLabsTTSProvider()
            self.assertTrue(provider.configured)
            self.assertTrue(provider.api_key)
            self.assertTrue(provider.voice_id)


if __name__ == "__main__":
    unittest.main()
