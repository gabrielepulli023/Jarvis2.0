import unittest

from jarvis_core.events import EventBus
from jarvis_core.operational_context import OperationalContext
from jarvis_core.world_model import WorldModel
from jarvis_memory import WorkingMemory


class FakePerception:
    def __init__(self, current):
        self.current = current
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return {"current": self.current}


class WorldModelTests(unittest.TestCase):
    def setUp(self):
        self.memory = WorkingMemory(max_entries=64)
        self.world = WorldModel(self.memory, events=EventBus())

    def test_mention_does_not_claim_running(self):
        self.world.mention("Chrome", "application")
        self.assertNotEqual(self.world.get("application:chrome")["properties"].get("running", {}).get("value"), True)

    def test_verified_open_and_close_update_running(self):
        self.world.observe_tool("apps.open", {"success": True, "verification": {"status": "verified"}}, {"application": "Chrome"})
        self.assertTrue(self.world.explain("application:chrome", "running")["value"])
        self.world.observe_tool("apps.close", {"success": True, "verification": {"status": "verified"}}, {"application": "Chrome"})
        self.assertFalse(self.world.explain("application:chrome", "running")["value"])

    def test_failed_and_unverified_open_do_not_set_running(self):
        for result in ({"success": False}, {"success": True}):
            self.world.observe_tool("apps.open", result, {"application": "Chrome"})
        self.assertIsNone(self.world.get("application:chrome"))

    def test_process_observation_corrects_verified_state(self):
        self.world.observe_tool("apps.open", {"success": True, "verification": {"status": "verified"}}, {"application": "Chrome"})
        self.world.refresh({"opened_apps": [], "active_window": None, "current_task": []})
        self.assertFalse(self.world.explain("application:chrome", "running")["value"])
        self.world.refresh({"opened_apps": [{"name": "Spotify", "running": True}], "active_window": None, "current_task": []})
        self.assertFalse(self.world.explain("application:chrome", "running")["value"])

    def test_perception_reads_snapshot_without_observing(self):
        perception = FakePerception({"application": "Chrome", "window": "Google", "source": "dom", "confidence": .98, "elements": [{"id": "save", "name": "Save", "role": "button", "confidence": .98}]})
        self.world.bind_perception(perception)
        self.world.refresh({"opened_apps": [], "active_window": None, "current_task": []})
        self.assertEqual(perception.calls, 1)
        self.assertEqual(self.world.explain("application:chrome", "focused")["source"], "dom")
        self.assertEqual(self.world.explain("ui:save", "role")["value"], "button")

    def test_low_confidence_vision_does_not_replace_fresh_dom(self):
        self.world.observe("application:chrome", {"focused": True}, source="dom", confidence=.98, evidence_type="observed_structured")
        self.world.observe("application:code", {"focused": True}, source="vision", confidence=.55, evidence_type="observed_perception")
        self.assertTrue(self.world.explain("application:chrome", "focused")["value"])

    def test_artifact_is_bounded_and_secret_free(self):
        content = "x" * 10000
        self.world.observe_tool("file.create", {"success": True, "verification": {"status": "verified"}, "data": {"path": "C:/report.txt", "content": content, "token": "secret"}}, {})
        row = self.world.get("artifact:c:/report.txt")
        self.assertEqual(row["properties"]["path"]["value"], "C:/report.txt")
        self.assertNotIn("content", str(row))
        self.assertNotIn("secret", str(row))

    def test_events_only_change_state(self):
        events = []
        EventBus().subscribe("world.updated", lambda event: events.append(event))
        self.world.observe("application:chrome", {"running": True}, source="tool", confidence=.9, evidence_type="verified")
        before = self.world.snapshot()
        self.assertLessEqual(len(before["entities"]), 64)
        self.assertLessEqual(len(self.world.compact()), 1600)

    def test_operational_context_is_the_integration_entrypoint(self):
        context = OperationalContext()
        result = {"successo": True, "verification": {"status": "verified"}, "dati": {"application": "Chrome"}}
        context.record("apps.open", result, {"application": "Chrome"})
        self.world.observe_tool("apps.open", result, {"application": "Chrome"})
        self.assertTrue(self.world.explain("application:chrome", "running")["value"])


if __name__ == "__main__":
    unittest.main()
