import unittest

from jarvis_hud.state_store import HUDStateStore


class HUDStateStoreTests(unittest.TestCase):
    def test_no_profile_selects_setup_without_fake_identity(self):
        store = HUDStateStore()
        state = store.ingest_snapshot({
            "state": {"identity": {"status": "setup_required", "authenticated": False}},
            "voice": {"state": "idle"}, "capabilities": [], "context": {},
        })
        self.assertEqual(state["mode"], "SETUP")
        self.assertFalse(state["identity"]["authenticated"])

    def test_camera_event_has_priority_and_stops_cleanly(self):
        store = HUDStateStore()
        active = store.ingest_event("camera.started", {"purpose": "identity", "camera": 0})
        self.assertTrue(active["camera"]["active"])
        self.assertEqual(active["mode"], "CAMERA")
        stopped = store.ingest_event("camera.stopped", {"purpose": "identity", "camera": 0})
        self.assertFalse(stopped["camera"]["active"])
        self.assertFalse(stopped["camera"]["privacy"])
        self.assertEqual(stopped["core_state"], "standby")

    def test_context_modes_are_derived_from_real_window_name(self):
        store = HUDStateStore()
        state = store.ingest_snapshot({"context": {"active_window": "Visual Studio Code"}})
        self.assertEqual(state["mode"], "CODING")

    def test_foreground_window_event_switches_to_trading(self):
        store = HUDStateStore()
        state = store.ingest_event("context.active_window", {"active_window": "TradingView - Chrome"})
        self.assertEqual(state["mode"], "TRADING")

    def test_string_voice_state_is_preserved_for_hud_normalization(self):
        store = HUDStateStore()
        state = store.ingest_event("state.changed", {"key": "voice", "value": "speaking"})
        self.assertEqual(state["voice"], "speaking")

    def test_empty_polling_context_does_not_erase_live_foreground_window(self):
        store = HUDStateStore()
        store.ingest_event("context.active_window", {"active_window": "TradingView - Chrome"})
        state = store.ingest_snapshot({"context": {"active_window": "", "last_tool": "web"}})
        self.assertEqual(state["context"]["active_window"], "TradingView - Chrome")
        self.assertEqual(state["mode"], "TRADING")

    def test_tool_event_prefers_specific_runtime_payload(self):
        store = HUDStateStore()
        state = store.ingest_event("tool.started", {"tool": "windows.show_desktop"})
        self.assertEqual(state["active_tool"], "windows.show_desktop")
        self.assertEqual(state["core_state"], "executing")
    def test_typed_state_partial_transcript_and_emergency_are_projected(self):
        store=HUDStateStore();state=store.ingest_event("assistant.state_changed",{"state":"verifying"})
        self.assertEqual(state["core_state"],"verifying")
        state=store.ingest_event("voice.partial",{"text":"apri chrome"});self.assertEqual(state["partial_transcript"],"apri chrome")
        state=store.ingest_event("emergency.stop",{"sequence":2});self.assertTrue(state["emergency"]["active"]);self.assertEqual(state["core_state"],"idle")


if __name__ == "__main__":
    unittest.main()
