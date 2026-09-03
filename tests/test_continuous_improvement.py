import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import adaptive_learning
from continuous_improvement import analyze_evaluations, write_analysis


class ContinuousImprovementTests(unittest.TestCase):
    def test_trend_analyzer_detects_scenario_regression(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "real-world-1.json").write_text(json.dumps({"automatic": {"passed": 2, "total": 2, "status": "PASS"}, "scenarios": [{"id": "x", "status": "PASS"}]}), encoding="utf-8")
            (root / "real-world-2.json").write_text(json.dumps({"automatic": {"passed": 1, "total": 2, "status": "FAIL"}, "scenarios": [{"id": "x", "status": "FAIL"}]}), encoding="utf-8")
            with patch("continuous_improvement.data_path", return_value=root):
                result = analyze_evaluations()
            self.assertEqual(result["status"], "REGRESSION")
            self.assertTrue(result["regressions"])

    def test_procedure_requires_approval_and_supports_dry_run(self):
        with tempfile.TemporaryDirectory() as folder:
            old = adaptive_learning.STORE
            adaptive_learning.STORE = Path(folder) / "procedures.json"
            try:
                mission = {"status": "completed", "request": "apri e controlla", "steps": [
                    {"tool": "apri_programma", "arguments": {"nome": "Chrome"}, "success": True, "verification": {"status": "verified"}},
                    {"tool": "chrome_snapshot", "arguments": {}, "success": True, "verification": {"status": "verified"}},
                ]}
                row = adaptive_learning.learn_completed_mission(mission)
                adaptive_learning.learn_completed_mission(mission)
                self.assertFalse(row.get("approved", False))
                self.assertTrue(adaptive_learning.simulate_procedure(row["signature"])["successo"])
                approved = adaptive_learning.approve_procedure(row["signature"])
                self.assertTrue(approved["approved"])
            finally:
                adaptive_learning.STORE = old

    def test_analysis_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            target = write_analysis({"status": "HEALTHY"}, Path(folder) / "trend.json")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["status"], "HEALTHY")
            self.assertFalse(target.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
