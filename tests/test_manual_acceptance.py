import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from tests.manual_windows_acceptance import audio_sample_test, desktop_test


class ManualAcceptanceTests(unittest.TestCase):
    def test_audio_sample_keeps_metrics_and_not_audio(self):
        module = types.ModuleType("sounddevice")
        module.rec = lambda frames, **_kwargs: np.full((frames, 1), 0.1, dtype=np.float32)
        module.wait = lambda: None
        with patch.dict(sys.modules, {"sounddevice": module}):
            measured = audio_sample_test(duration=1)
        self.assertEqual(measured["status"], "PASS")
        self.assertFalse(measured["evidence"]["persisted"])
        self.assertNotIn("samples", measured["evidence"])

    def test_desktop_output_path_is_confined(self):
        with self.assertRaises(ValueError):
            desktop_test(__import__("tempfile").gettempdir())


if __name__ == "__main__":
    unittest.main()
