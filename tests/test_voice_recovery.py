import unittest
from unittest.mock import patch

import voice


class VoiceRecoveryTests(unittest.TestCase):
    def test_remote_stt_failure_keeps_local_vosk_text(self):
        with patch.object(voice, "trascrivi", side_effect=TimeoutError("remote timeout")):
            text, remote = voice._transcribe_with_fallback("unused.wav", "apri chrome")

        self.assertEqual(text, "apri chrome")
        self.assertIsNone(remote)

    def test_empty_remote_stt_result_keeps_local_vosk_text(self):
        with patch.object(voice, "trascrivi", return_value=""):
            text, remote = voice._transcribe_with_fallback("unused.wav", "mostra desktop")

        self.assertEqual(text, "mostra desktop")
        self.assertIsNone(remote)


if __name__ == "__main__":
    unittest.main()
