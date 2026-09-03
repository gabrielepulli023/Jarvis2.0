import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import automation_engine


class AutomationRoutineValidationTests(unittest.TestCase):
    def test_add_after_rejects_non_positive_delay_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "routines.json"
            with patch.object(automation_engine, "STORE", store):
                for value in (0, -1):
                    with self.assertRaisesRegex(ValueError, "greater than zero"):
                        automation_engine.add_after(value, "test")
                self.assertFalse(store.exists())


if __name__ == "__main__":
    unittest.main()
