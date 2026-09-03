import unittest

from jarvis_core.events import EventBus
from jarvis_core.operational_context import OperationalContext
from jarvis_core.world_model import WorldModel
from jarvis_system.context import ContextEngine
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
        self.world.refresh({"os_processes": [{"name": "Spotify.exe", "exe": "C:/Spotify/Spotify.exe", "pid": 2}], "os_processes_available": True, "active_window": None, "current_task": []})
        self.assertFalse(self.world.explain("application:chrome", "running")["value"])

    def test_managed_process_absence_does_not_close_application(self):
        self.world.observe_tool("apps.open", {"success": True, "verification": {"status": "verified"}}, {"application": "Chrome"})
        self.world.refresh({"opened_apps": [], "managed_processes": [], "active_window": None, "current_task": []})
        self.assertTrue(self.world.explain("application:chrome", "running")["value"])

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

    def test_focus_is_exclusive_and_structured_observation_wins(self):
        self.world.observe("application:chrome", {"focused": True}, source="dom", confidence=.98, evidence_type="observed_structured")
        self.world.observe("application:code", {"focused": True}, source="vision", confidence=.55, evidence_type="observed_perception")
        self.assertIsNone(self.world.get("application:code"))
        self.world.observe("application:code", {"focused": True}, source="runtime_context", confidence=.98, evidence_type="observed_structured")
        self.assertFalse(self.world.explain("application:chrome", "focused")["value"])
        self.assertTrue(self.world.explain("application:code", "focused")["value"])

    def test_application_aliases_converge(self):
        self.world.observe_tool("apps.open", {"success": True, "verification": {"status": "verified"}}, {"name": "Visual Studio Code", "executable": r"C:\\Program Files\\Microsoft VS Code\\Code.exe"})
        self.world.observe("application:Code.exe", {"running": True}, source="process_snapshot", confidence=.98, evidence_type="observed_structured")
        entities = self.world.find("application", limit=20)
        self.assertEqual(len(entities), 1)
        self.assertIn("Visual Studio Code", entities[0]["properties"]["aliases"]["value"])

    def test_artifact_is_bounded_and_secret_free(self):
        content = "x" * 10000
        self.world.observe_tool("file.create", {"success": True, "verification": {"status": "verified"}, "data": {"path": "C:/report.txt", "content": content, "token": "secret"}}, {})
        row = self.world.get("artifact:c:/report.txt")
        self.assertEqual(row["properties"]["path"]["value"], "C:/report.txt")
        self.assertNotIn("content", str(row))
        self.assertNotIn("secret", str(row))

    def test_events_only_change_state(self):
        events = []
        bus = EventBus()
        bus.subscribe("world.updated", lambda event: events.append(event))
        world = WorldModel(self.memory, events=bus)
        world.observe("application:chrome", {"running": True}, source="tool", confidence=.9, evidence_type="verified")
        world.observe("application:chrome", {"running": True}, source="tool", confidence=.9, evidence_type="verified")
        world.observe("application:chrome", {"running": False}, source="tool", confidence=.9, evidence_type="verified")
        self.assertEqual(len(events), 2)
        before = world.snapshot()
        self.assertLessEqual(len(before["entities"]), 64)
        self.assertLessEqual(len(self.world.compact()), 1600)

    def test_compact_honors_small_limit(self):
        self.world.observe("application:chrome", {"running": True, "aliases": ["Chrome"]}, source="tool", confidence=.9, evidence_type="verified")
        self.assertLessEqual(len(self.world.compact(max_chars=300)), 300)

    def test_operational_context_is_the_integration_entrypoint(self):
        context = OperationalContext()
        result = {"successo": True, "verification": {"status": "verified"}, "dati": {"application": "Chrome"}}
        context.record("apps.open", result, {"application": "Chrome"})
        self.world.observe_tool("apps.open", result, {"application": "Chrome"})
        self.assertTrue(self.world.explain("application:chrome", "running")["value"])

    def test_context_managed_processes_do_not_count_as_os_absence(self):
        class ManagedOnly:
            def snapshot(self):
                return [{"id": "owned", "pid": 1, "command": ("helper",), "running": True}]

        class State:
            def snapshot(self):
                return {}

        class Missions:
            def recent(self, _limit=1):
                return []

        memory_store = type("MemoryStore", (), {"working": self.memory})()
        context = ContextEngine(EventBus(), State(), ManagedOnly(), memory_store, Missions(), world=self.world)
        self.world.observe_tool("apps.open", {"success": True, "verification": {"status": "verified"}}, {"application": "Chrome"})
        snapshot = context.snapshot()
        self.assertTrue(self.world.explain("application:chrome", "running")["value"])
        self.assertIn("managed_processes", snapshot)
        context.close()


if __name__ == "__main__":
    unittest.main()
