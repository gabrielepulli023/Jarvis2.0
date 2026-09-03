import queue
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


if __name__ == "__main__":
    unittest.main()
