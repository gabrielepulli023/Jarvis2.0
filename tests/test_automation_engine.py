import tempfile
import unittest
from datetime import datetime, timedelta
import threading
from datetime import datetime, timedelta
from pathlib import Path

from jarvis_automation import AutomationEngine


class AutomationEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, dispatcher, sleeper=lambda _: None):
        return AutomationEngine(Path(self.temp.name) / "automation.db", dispatcher, sleeper)

    def test_chained_actions_retry_and_history(self):
        calls = []

        def dispatch(action):
            calls.append(action["command"])
            if len(calls) == 1:
                return {"success": False, "message": "temporary"}
            return {"success": True, "message": "ok"}

        engine = self.engine(dispatch)
        item = engine.create("Morning", "daily", "08:30", ["first", "second"], retries=1)
        result = engine.execute(item, "daily:2026-08-10:08:30")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(calls, ["first", "first", "second"])
        self.assertEqual(engine.report()["runs"]["completed"]["count"], 1)

    def test_idempotency_prevents_duplicate_side_effects(self):
        calls = []
        engine = self.engine(lambda action: calls.append(action) or {"success": True})
        item = engine.create("Once", "once", "2026-08-10T12:00:00", ["go"])
        first = engine.execute(item, "unique-event")
        duplicate = engine.execute(item, "unique-event")
        self.assertEqual(first.status, "completed")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(len(calls), 1)

    def test_daily_once_interval_and_cron_due(self):
        now = datetime(2026, 8, 10, 8, 30)
        engine = self.engine(lambda _: {"success": True})
        engine.create("daily", "daily", "08:30", ["a"])
        engine.create("once", "once", (now - timedelta(minutes=1)).isoformat(), ["b"])
        engine.create("interval", "interval", "60", ["c"])
        engine.create("cron", "cron", "30 8 * * *", ["d"])
        self.assertEqual(len(engine.due(now)), 4)
        engine.run_due(now)
        self.assertEqual(len(engine.due(now)), 0)

    def test_interval_trigger_rejects_non_positive_seconds(self):
        engine = self.engine(lambda _: {"success": True})
        for value in ("0", "-1", "not-a-number"):
            with self.assertRaisesRegex(ValueError, "positive"):
                engine.create("invalid", "interval", value, ["noop"])

    def test_time_triggers_reject_malformed_values(self):
        engine = self.engine(lambda _: {"success": True})
        cases = (("once", "tomorrow"), ("daily", "25:30"), ("cron", "every hour"))
        for trigger_type, value in cases:
            with self.assertRaises(ValueError):
                engine.create("invalid", trigger_type, value, ["noop"])

    def test_legacy_malformed_schedule_is_skipped_by_due(self):
        now = datetime(2026, 8, 10, 8, 30)
        engine = self.engine(lambda _: {"success": True})
        valid = engine.create("valid", "daily", "08:30", ["ok"])
        with engine._connect() as db:
            db.execute("INSERT INTO automations VALUES(?,?,?,?,?,?,?,?,?)", ("bad", "bad", "once", "broken", "[]", 1, 0, now.isoformat(), now.isoformat()))
        due = engine.due(now)
        self.assertEqual([item[0]["id"] for item in due], [valid])

    def test_corrupt_historical_outputs_do_not_break_history_or_deduplication(self):
        engine = self.engine(lambda _: {"success": True})
        automation_id = engine.create("history", "event", "x", ["noop"])
        first = engine.execute(automation_id, "event-1")
        self.assertEqual(first.status, "completed")
        with engine._connect() as db:
            db.execute("UPDATE automation_runs SET outputs_json=?", ("{broken",))
        history = engine.history()
        self.assertEqual(history[0]["outputs"], [])
        duplicate = engine.execute(automation_id, "event-1")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.outputs, ())

    def test_history_uses_safe_default_for_invalid_limit(self):
        engine = self.engine(lambda _: {"success": True})
        automation_id = engine.create("history", "event", "x", ["noop"])
        engine.execute(automation_id, "event-1")
        self.assertEqual(len(engine.history("invalid")), 1)
        self.assertEqual(len(engine.history(None)), 1)

    def test_corrupt_persisted_actions_do_not_hide_valid_automations(self):
        engine = self.engine(lambda _: {"success": True})
        valid = engine.create("valid", "event", "x", ["ok"])
        with engine._connect() as db:
            db.execute("UPDATE automations SET actions_json=? WHERE id=?", ("{broken", valid))
            db.execute(
                "INSERT INTO automations VALUES(?,?,?,?,?,?,?,?,?)",
                ("healthy", "healthy", "event", "y", '[{"command":"ok"}]', 1, 0, "2026-01-01", "2026-01-01"),
            )
        rows = engine.list(enabled_only=True)
        self.assertEqual([row["id"] for row in rows], ["healthy"])

    def test_stale_running_execution_can_be_recovered_once(self):
        calls = []
        engine = self.engine(lambda action: calls.append(action) or {"success": True})
        automation_id = engine.create("recover", "event", "x", ["ok"])
        engine.execute(automation_id, "event-1")
        old = (datetime.now() - timedelta(minutes=20)).isoformat()
        with engine._connect() as db:
            db.execute(
                "UPDATE automation_runs SET status=?,started_at=?,finished_at=? WHERE automation_id=? AND trigger_key=?",
                ("running", old, old, automation_id, "event-1"),
            )
        recovered = engine.execute(automation_id, "event-1")
        self.assertEqual(recovered.status, "completed")
        self.assertFalse(recovered.duplicate)
        self.assertEqual(len(calls), 2)

    def test_event_and_voice_triggers(self):
        calls = []
        engine = self.engine(lambda action: calls.append(action["command"]) or {"success": True})
        engine.create("download", "event", "file.created", ["scan"])
        engine.create("voice", "voice", "modalità lavoro", ["focus"])
        event = engine.handle_event("file.created", {"event_id": "42"})
        voice = engine.handle_event("voice.input", {"event_id": "43", "text": "Attiva modalità lavoro"})
        self.assertEqual([row.status for row in event + voice], ["completed", "completed"])
        self.assertEqual(calls, ["scan", "focus"])

    def test_failures_exhaust_retry_and_are_audited(self):
        engine = self.engine(lambda _: {"success": False, "message": "no"})
        item = engine.create("failure", "event", "x", ["bad"], retries=2)
        result = engine.execute(item, "event-1")
        self.assertEqual((result.status, result.attempts), ("failed", 3))
        self.assertIn("no", result.error)
        self.assertEqual(engine.history()[0]["status"], "failed")

    def test_concurrent_duplicate_is_reserved_before_dispatch(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def dispatch(action):
            calls.append(action)
            entered.set()
            release.wait(2)
            return {"success": True}

        engine = self.engine(dispatch)
        item = engine.create("concurrent", "event", "x", ["go"])
        results = []
        first = threading.Thread(target=lambda: results.append(engine.execute(item, "same")))
        first.start()
        self.assertTrue(entered.wait(1))
        second = engine.execute(item, "same")
        release.set()
        first.join(2)
        self.assertTrue(second.duplicate)
        self.assertEqual(second.status, "running")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
