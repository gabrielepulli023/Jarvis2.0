import json
import tempfile
import unittest
from pathlib import Path

from reliability_engine import ReliabilityEngine


class ReliabilityEngineTests(unittest.TestCase):
    def test_records_kpis_and_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missions.json"
            engine = ReliabilityEngine(path, version="2.0.0")
            mission = engine.start("open app", confidence=0.8, api_key="do-not-store")
            engine.event(mission, "tool", name="open", success=True)
            engine.event(mission, "retry")
            row = engine.finish(mission, confidence=0.95, verified=True)
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["api_key"], "[REDACTED]")
            self.assertEqual(engine.report()["kpi"]["task_success_rate"], 1.0)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("do-not-store", json.dumps(persisted))

    def test_unknown_mission_is_not_falsely_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = ReliabilityEngine(Path(folder) / "missions.json")
            self.assertIsNone(engine.finish("missing"))
            self.assertFalse(engine.event("missing", "tool", name="x"))


if __name__ == "__main__":
    unittest.main()
