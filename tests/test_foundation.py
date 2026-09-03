import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.config import ConfigManager
from jarvis_core.logging import configure_logging
from jarvis_core.events import EventBus
from jarvis_core.health import HealthManager, HealthStatus
from jarvis_core.processes import ProcessManager
from jarvis_core.runtime import CoreRuntime
from jarvis_core.state import StateManager
from jarvis_core.watchdog import Watchdog


class FoundationTests(unittest.TestCase):
    def test_event_bus_isolates_failed_subscriber(self):
        bus = EventBus()
        received = []
        bus.subscribe("x", lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
        bus.subscribe("x", received.append)
        bus.publish("x", {"value": 1})
        self.assertEqual(received[0].payload["value"], 1)

    def test_state_is_copied_and_emits_changes(self):
        bus = EventBus()
        events = []
        bus.subscribe("state.changed", events.append)
        state = StateManager(bus)
        source = {"items": []}
        state.set("mission", source)
        source["items"].append("mutation")
        self.assertEqual(state.get("mission"), {"items": []})
        self.assertEqual(len(events), 1)

    def test_health_and_watchdog_report_failure(self):
        health = HealthManager(EventBus())
        watchdog = Watchdog(health)
        watchdog.register("voice", lambda: False)
        self.assertFalse(watchdog.check_now("voice"))
        self.assertEqual(health.snapshot()["voice"]["status"], HealthStatus.FAILED)

    def test_managed_process_is_observable(self):
        manager = ProcessManager(EventBus())
        item = manager.start([sys.executable, "-c", "import time; time.sleep(2)"], mission_id="m1")
        self.assertTrue(manager.snapshot()[0]["running"])
        self.assertTrue(manager.terminate(item.id))

    def test_runtime_lifecycle(self):
        runtime = CoreRuntime()
        runtime.start()
        self.assertTrue(runtime.state.get("running"))
        self.assertIn("health", runtime.diagnostics())
        skills = {row["name"] for row in runtime.skills.list()}
        self.assertTrue(
            {"broker.driver_list", "broker.update_scan", "broker.firewall_rule_add", "broker.task_disable"} <= skills
        )
        runtime.stop()
        self.assertFalse(runtime.state.get("running"))
        runtime.stop()
        self.assertFalse(runtime.state.get("running"))

    def test_config_layers_environment_with_types(self):
        with patch.dict(os.environ, {"JARVIS_ENABLED": "false", "JARVIS_LIMIT": "7"}):
            config = ConfigManager({"enabled": True, "limit": 2})
        self.assertFalse(config.get("enabled"))
        self.assertEqual(config.get("limit"), 7)

    def test_json_logging_writes_structured_record(self):
        path = Path(tempfile.gettempdir()) / "jarvis_foundation_test.jsonl"
        path.unlink(missing_ok=True)
        logger = configure_logging(path)
        logger.info("diagnostic.completed", extra={"mission_id": "m1"})
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["event"], "diagnostic.completed")
        self.assertEqual(row["mission_id"], "m1")


if __name__ == "__main__":
    unittest.main()
