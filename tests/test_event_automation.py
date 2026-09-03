import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import event_automation


class EventAutomationValidationTests(unittest.TestCase):
    def test_empty_command_is_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "rules.json"
            with patch.object(event_automation, "STORE", store):
                with self.assertRaisesRegex(ValueError, "comando"):
                    event_automation.add_rule("process_started", "notepad.exe", "   ")
                self.assertFalse(store.exists())

    def test_malformed_rule_does_not_block_following_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "rules.json"
            with patch.object(event_automation, "STORE", store):
                event_automation._save([
                    {"id": "bad", "type": "cpu_above", "value": "not-a-number", "command": "bad", "enabled": True},
                    {"id": "good", "type": "process_started", "value": "notepad.exe", "command": "good", "enabled": True},
                ])
                worker = event_automation.EventAutomationWorker()
                commands, notices = [], []
                worker.command.connect(commands.append)
                worker.notice.connect(notices.append)
                with patch.object(event_automation.psutil, "process_iter", return_value=[SimpleNamespace(info={"name": "notepad.exe"})]):
                    worker._check()
                self.assertEqual(commands, ["good"])
                self.assertTrue(any("ignorata" in notice for notice in notices))


if __name__ == "__main__":
    unittest.main()
