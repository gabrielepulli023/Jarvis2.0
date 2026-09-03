import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from jarvis_automation import AutomationEngine
from jarvis_core.emergency import EmergencyStopCoordinator
from jarvis_core.events import EventBus


class EmergencyStopTests(unittest.TestCase):
    def test_callbacks_are_isolated_prioritized_and_resettable(self):
        bus = EventBus(); events = []; bus.subscribe("*", events.append)
        coordinator = EmergencyStopCoordinator(bus); called = []
        coordinator.register("ok", lambda: called.append("ok"))
        coordinator.register("broken", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = coordinator.trigger()
        self.assertTrue(coordinator.active); self.assertEqual(called, ["ok"]); self.assertEqual(len(result.failures), 1)
        self.assertEqual(events[0].priority, 1000)
        coordinator.reset(); self.assertFalse(coordinator.active)

    def test_paused_automation_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            dispatcher = Mock(return_value={"success": True})
            engine = AutomationEngine(Path(directory) / "automation.db", dispatcher)
            identity = engine.create("x", "event", "go", [{"command": "x"}])
            engine.pause(); result = engine.execute(identity, "one")
            self.assertEqual(result.status, "cancelled"); dispatcher.assert_not_called()
            engine.resume(); self.assertFalse(engine.paused)


if __name__ == "__main__": unittest.main()
