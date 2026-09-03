import json
import tempfile
import unittest
from pathlib import Path

from evaluation_pack import SCENARIOS, run_automatic, write_report


class EvaluationPackTests(unittest.TestCase):
    def test_automatic_scenarios_pass_and_are_non_sensitive(self):
        report = run_automatic()
        self.assertEqual(report["automatic"]["status"], "PASS")
        self.assertEqual(report["automatic"]["passed"], len(SCENARIOS))
        self.assertFalse(report["sensitive_data_persisted"])
        self.assertTrue(all(row["provider"]["provider"] for row in report["scenarios"]))

    def test_report_is_atomic_and_machine_readable(self):
        report = run_automatic()
        with tempfile.TemporaryDirectory() as folder:
            path = write_report(report, Path(folder) / "evaluation.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["automatic"]["status"], "PASS")
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
