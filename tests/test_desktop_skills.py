import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_skills import SkillRegistry
from jarvis_skills.desktop import register_browser_skills, register_desktop_skills


class DesktopSkillTests(unittest.TestCase):
    def registry(self):
        return SkillRegistry(Path(tempfile.mkdtemp()) / "metrics.db", lambda capability: True)

    def test_registers_windows_ui_and_browser_manifests(self):
        registry = self.registry()
        register_desktop_skills(registry)
        register_browser_skills(registry)
        names = {x["name"] for x in registry.list()}
        self.assertTrue(
            {
                "windows.list",
                "windows.focus",
                "windows.move",
                "ui.inspect",
                "ui.invoke",
                "browser.dom",
                "browser.snapshot",
                "browser.visual",
                "mouse.move",
                "mouse.move_relative",
                "mouse.click",
                "mouse.double_click",
                "mouse.right_click",
                "mouse.drag",
                "mouse.scroll",
                "keyboard.press",
                "keyboard.hotkey",
                "keyboard.key_down",
                "keyboard.key_up",
            }.issubset(names)
        )

    def test_dom_action_requires_fresh_matching_snapshot(self):
        registry = self.registry()
        register_browser_skills(registry)
        snapshots = iter(
            [
                {"successo": True, "dati": {"received_at": 1, "title": "old"}},
                {"successo": True, "dati": {"received_at": 2, "title": "new"}},
            ]
        )
        chrome = types.ModuleType("chrome_bridge")
        chrome.chrome_snapshot = lambda: next(snapshots)
        chrome.chrome_action = lambda *args: {"successo": True}
        with patch.dict(sys.modules, {"chrome_bridge": chrome}):
            result = registry.execute(
                "browser.dom", action="click_text", target="Next", expected={"title": "new"}, timeout=0.2
            )
        self.assertTrue(result.success)
        self.assertTrue(result.data["verified"])

    def test_dom_action_does_not_claim_unverified_success(self):
        registry = self.registry()
        register_browser_skills(registry)
        chrome = types.ModuleType("chrome_bridge")
        chrome.chrome_snapshot = lambda: {"successo": True, "dati": {"received_at": 1, "title": "old"}}
        chrome.chrome_action = lambda *args: {"successo": True}
        visual = types.ModuleType("visual_agent")
        visual.visual_task = lambda *args, **kwargs: {"successo": False, "messaggio": "vision unavailable"}
        with patch.dict(sys.modules, {"chrome_bridge": chrome, "visual_agent": visual}):
            result = registry.execute(
                "browser.dom", action="click_text", target="Next", expected={"title": "new"}, timeout=0.2
            )
        self.assertFalse(result.success)
        self.assertIn("non verificato", result.message)


if __name__ == "__main__":
    unittest.main()
