import tempfile
import time
import unittest
from pathlib import Path

import chrome_bridge


class BrowserHardeningTests(unittest.TestCase):
    def setUp(self):
        chrome_bridge._discard_pending_commands()
        with chrome_bridge._LOCK: chrome_bridge._RESULTS.clear(); chrome_bridge._SNAPSHOT.clear()

    def test_extension_config_is_local_and_contains_runtime_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(chrome_bridge.write_extension_config(directory))
            self.assertEqual(path.name, "local_config.js"); self.assertIn(chrome_bridge.TOKEN, path.read_text(encoding="utf-8"))

    def test_command_has_identity_expiry_and_bounded_queue(self):
        with chrome_bridge._LOCK: chrome_bridge._SNAPSHOT["received_at"] = time.time()
        first = chrome_bridge.chrome_action("navigate", "https://example.com")
        command = chrome_bridge._COMMANDS.get_nowait(); chrome_bridge._COMMANDS.task_done()
        self.assertEqual(command["request_id"], first["request_id"]); self.assertGreater(command["expires_at"], command["created_at"])
        for index in range(100): chrome_bridge.chrome_action("scroll", value=str(index))
        self.assertLessEqual(chrome_bridge._COMMANDS.qsize(), 64)

    def test_correlated_result_and_redaction(self):
        with chrome_bridge._LOCK: chrome_bridge._RESULTS["r1"] = {"request_id":"r1","ok":True,"received_at":time.time()}
        self.assertTrue(chrome_bridge.chrome_command_status("r1")["successo"])
        safe = chrome_bridge._redact({"text":"API_KEY=secret words", "cookie":"bad"})
        self.assertNotIn("secret", safe["text"]); self.assertNotIn("cookie", safe)

    def test_unknown_browser_action_is_denied(self):
        self.assertFalse(chrome_bridge.chrome_action("execute_javascript", value="alert(1)")["successo"])


if __name__ == "__main__": unittest.main()
