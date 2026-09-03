import unittest

from jarvis_core.mode import RuntimeMode


class SafeModeTests(unittest.TestCase):
    def test_flag_enables_safe_mode(self):
        self.assertTrue(RuntimeMode.detect(["--safe"]).safe)

    def test_safe_mode_is_chat_and_diagnostics_only(self):
        mode = RuntimeMode(safe=True)
        self.assertTrue(mode.permits("READ_FILES"))
        self.assertFalse(mode.permits("WRITE_FILES"))
        self.assertFalse(mode.permits("PROCESS_CONTROL"))
        self.assertFalse(mode.permits("SYSTEM_SETTINGS"))

    def test_normal_mode_preserves_capabilities(self):
        self.assertTrue(RuntimeMode(safe=False).permits("SYSTEM_SETTINGS"))


if __name__ == "__main__":
    unittest.main()
