import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from jarvis_windows import InputController, WindowInfo, WindowManager, WindowsUIAgent
from jarvis_skills.desktop import register_desktop_skills
from jarvis_skills.registry import SkillRegistry


class WindowsAgentTests(unittest.TestCase):
    def test_text_input_is_exposed_as_a_structured_skill(self):
        with TemporaryDirectory() as temporary:
            registry = SkillRegistry(Path(temporary) / "metrics.db")
            register_desktop_skills(registry)
            self.assertIsNotNone(registry.manifest("keyboard.write"))

    def test_input_controller_validates_virtual_screen_and_releases_keys(self):
        backend = Mock()
        backend.KEYBOARD_KEYS = ["ctrl", "a"]
        backend.position.return_value = type("Point", (), {"x": 0, "y": 0})()
        controller = InputController(backend, bounds=lambda: (-100, -50, 300, 200))
        self.assertTrue(controller.move_absolute(-50, 10)["success"])
        self.assertTrue(controller.move_relative(10, 20)["success"])
        self.assertTrue(controller.hotkey(["ctrl", "a"])["success"])
        self.assertEqual(controller.write("hello")["data"]["characters"], 5)
        controller.key_down("ctrl")
        controller.release_all()
        backend.keyUp.assert_called_with("ctrl")
        with self.assertRaises(ValueError):
            controller.move_absolute(500, 500)
        with self.assertRaises(ValueError):
            controller.click(button="side")
        with self.assertRaises(ValueError):
            controller.write("x" * 10_001)

    def test_window_manager_lists_finds_and_snaps_across_monitors(self):
        backend = Mock()
        backend.list_windows.return_value = [
            WindowInfo(10, "Chrome", 5, "chrome.exe", 0, 0, 800, 600, 1, "normal", True)
        ]
        backend.work_areas.return_value = [(-1920, 0, 0, 1080), (0, 0, 2560, 1440)]
        backend.move.return_value = True
        manager = WindowManager(backend)
        self.assertEqual(manager.active().title, "Chrome")
        self.assertTrue(manager.snap("chrome", "right", 1))
        backend.move.assert_called_once_with(10, 1280, 0, 1280, 1440)

    def test_invalid_monitor_and_tiny_resize_are_rejected(self):
        backend = Mock()
        backend.list_windows.return_value = [WindowInfo(1, "X", 1, None, 0, 0, 100, 100, 1, "normal", True)]
        backend.work_areas.return_value = [(0, 0, 1000, 800)]
        manager = WindowManager(backend)
        with self.assertRaises(ValueError):
            manager.snap("X", "left", 2)
        with self.assertRaises(ValueError):
            manager.move_resize("X", 0, 0, 20, 20)

    def test_uia_finds_reads_and_waits_without_coordinate_fallback(self):
        state = {"visible": True}

        def observe():
            elements = [{"name": "Salva", "automation_id": "save", "type": "Button"}] if state["visible"] else []
            return {"successo": True, "dati": {"window": "Editor", "elements": elements}}

        agent = WindowsUIAgent(observe)
        self.assertEqual(agent.find_element("save", control_type="Button")["name"], "Salva")
        self.assertEqual(agent.read_text("save"), "Salva")
        state["visible"] = False
        self.assertTrue(agent.wait_until_hidden("save", timeout=0.05, interval=0.01))

    def test_uia_targets_an_explicit_window_handle(self):
        observer = Mock(return_value={"successo": True, "dati": {"window": "Editor", "elements": []}})
        agent = WindowsUIAgent(observer)
        self.assertEqual(agent._snapshot(4242)["window"], "Editor")
        observer.assert_called_once_with(4242)


if __name__ == "__main__":
    unittest.main()
