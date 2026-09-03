import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis_core.diagnostics import DiagnosticsRunner
from jarvis_core.health import HealthManager
from jarvis_core.events import EventBus
from jarvis_core.watchdog import Watchdog


class DiagnosticsTests(unittest.TestCase):
    def test_checks_runtime_files_dependencies_and_sqlite_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("main.py", "brain.py", "hud.py"):
                (root / name).write_text("", encoding="utf-8")
            (root / "jarvis_core").mkdir()
            (root / "jarvis_core" / "runtime.py").write_text("", encoding="utf-8")
            db = sqlite3.connect(root / "state.db")
            try:
                db.execute("CREATE TABLE test(id INTEGER)")
                db.commit()
            finally:
                db.close()
            report = DiagnosticsRunner(root, root).run()
        self.assertNotEqual(report["status"], "failed")
        self.assertTrue(any(row["name"] == "sqlite:state.db" and row["status"] == "healthy" for row in report["checks"]))

    def test_missing_critical_file_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            report = DiagnosticsRunner(Path(folder), Path(folder)).run()
        self.assertEqual(report["status"], "failed")
        self.assertGreaterEqual(report["summary"]["failed"], 1)


class SelfHealingWatchdogTests(unittest.TestCase):
    def test_recovery_runs_only_after_threshold_and_resets_when_healthy(self):
        state = {"healthy": False, "recoveries": 0}

        def recover():
            state["recoveries"] += 1
            state["healthy"] = True
            return True

        watchdog = Watchdog(HealthManager(EventBus()))
        watchdog.register("service", lambda: state["healthy"], recover=recover, failure_threshold=2)
        self.assertFalse(watchdog.check_now("service"))
        self.assertEqual(state["recoveries"], 0)
        self.assertFalse(watchdog.check_now("service"))
        self.assertEqual(state["recoveries"], 1)
        self.assertTrue(watchdog.check_now("service"))
        self.assertEqual(watchdog._probes["service"].failures, 0)


if __name__ == "__main__":
    unittest.main()
