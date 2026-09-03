import queue
import inspect
import unittest
from unittest.mock import patch

import wakeword


class WakewordQueueTests(unittest.TestCase):
    def test_callback_keeps_queue_bounded_and_recent(self):
        with patch.object(wakeword, "audio_queue", queue.Queue(maxsize=2)):
            wakeword.callback(b"one", 1, None, None)
            wakeword.callback(b"two", 1, None, None)
            wakeword.callback(b"three", 1, None, None)
            self.assertEqual(wakeword.audio_queue.qsize(), 2)
            self.assertEqual(wakeword.audio_queue.get_nowait(), b"two")
            self.assertEqual(wakeword.audio_queue.get_nowait(), b"three")

    def test_speaker_lock_rejects_unmatched_voice_before_stt(self):
        with patch.object(wakeword, "session_profile", return_value=None), patch("settings_store.get_setting", return_value=True), patch(
            "jarvis_identity.IdentityService.recognize_voice_samples", return_value={"matched": False}
        ):
            self.assertFalse(wakeword._default_speaker_verifier(b"\x00\x01" * 8000, 16000))

    def test_speaker_lock_accepts_matching_voice(self):
        with patch.object(wakeword, "session_profile", return_value=None), patch("settings_store.get_setting", return_value=True), patch(
            "jarvis_identity.IdentityService.recognize_voice_samples", return_value={"matched": True}
        ):
            self.assertTrue(wakeword._default_speaker_verifier(b"\x00\x01" * 8000, 16000))

    def test_development_ceo_bypasses_speaker_authentication(self):
        with patch.object(wakeword, "session_profile", return_value={"method": "development_auto_ceo"}), patch(
            "jarvis_identity.IdentityService.recognize_voice_samples"
        ) as recognize:
            self.assertTrue(wakeword._default_speaker_verifier(b"\x00\x01" * 8000, 16000))
        recognize.assert_not_called()

    def test_local_wake_recovery_keeps_wake_only_fallback(self):
        transcriber = type("FakeTranscriber", (), {
            "__init__": lambda self: None,
            "feed": lambda self, chunk: None,
            "finish": lambda self: "rumore",
        })
        with patch("transcriber.StreamingTranscriber", transcriber):
            self.assertEqual(wakeword._recupera_frase_completa([b"pcm"]), "jarvis")

    def test_local_wake_recovery_returns_unrestricted_phrase_and_is_volatile(self):
        transcriber = type("FakeTranscriber", (), {
            "__init__": lambda self: None,
            "feed": lambda self, chunk: None,
            "finish": lambda self: "jarvis apri chrome",
        })
        with patch("transcriber.StreamingTranscriber", transcriber):
            wakeword._last_wake_text = wakeword._recupera_frase_completa([b"pcm"])
        self.assertEqual(wakeword.recupera_frase_wake(), "jarvis apri chrome")
        self.assertIsNone(wakeword.recupera_frase_wake())

    def test_wake_recovery_does_not_call_openai_or_write_audio(self):
        transcriber = type("FakeTranscriber", (), {
            "__init__": lambda self: None,
            "feed": lambda self, chunk: None,
            "finish": lambda self: "jarvis apri chrome",
        })
        with patch("transcriber.StreamingTranscriber", transcriber), patch("transcriber.client") as client:
            self.assertEqual(wakeword._recupera_frase_completa([b"pcm"]), "jarvis apri chrome")
        client.assert_not_called()

    def test_recent_audio_buffer_is_bounded_to_five_seconds(self):
        self.assertEqual(wakeword._recent_audio.maxlen, 40)
        self.assertEqual(40 * wakeword.BLOCK_SIZE / wakeword.SAMPLE_RATE, 5.0)

    def test_primary_wake_grammar_remains_conservative(self):
        source = inspect.getsource(wakeword.aspetta_jarvis)
        self.assertIn('["jarvis", "jarvi", "iarvis", "gervis", "jarves", "[unk]"]', source)


if __name__ == "__main__":
    unittest.main()
