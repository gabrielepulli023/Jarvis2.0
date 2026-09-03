import json
import unittest
from unittest.mock import patch

from voice import _barge_wake_word_detected


class _FinalRecognizer:
    def __init__(self, text):
        self.text = text

    def AcceptWaveform(self, _frame):
        return True

    def Result(self):
        return json.dumps({"text": self.text})


class BargeInWakeWordTests(unittest.TestCase):
    def detect(self, text):
        with patch("wakeword.contiene_jarvis", lambda value: "jarvis" in (value or "").lower()):
            return _barge_wake_word_detected(_FinalRecognizer(text), b"audio")

    def test_silence_does_not_interrupt(self):
        self.assertFalse(self.detect(""))

    def test_loud_noise_does_not_interrupt(self):
        self.assertFalse(self.detect("rumore"))

    def test_generic_speech_does_not_interrupt(self):
        self.assertFalse(self.detect("come stai oggi"))

    def test_video_audio_does_not_interrupt(self):
        self.assertFalse(self.detect("musica video televisione"))

    def test_final_jarvis_interrupts(self):
        self.assertTrue(self.detect("jarvis"))

    def test_jarvis_followed_by_request_interrupts(self):
        self.assertTrue(self.detect("jarvis apri il browser"))

    def test_standby_wake_word_logic_remains_unchanged(self):
        import wakeword

        self.assertTrue(wakeword.contiene_jarvis("jarvis"))
        self.assertFalse(wakeword.contiene_jarvis("musica"))


if __name__ == "__main__":
    unittest.main()
