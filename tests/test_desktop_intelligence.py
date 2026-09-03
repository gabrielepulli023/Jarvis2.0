import unittest
from unittest.mock import patch

import desktop_intelligence


class DesktopIntelligenceTests(unittest.TestCase):
    @patch("desktop_intelligence._run")
    def test_inspect_targets_handle(self, run):
        run.return_value = {"window": "Editor", "elements": []}
        self.assertTrue(desktop_intelligence.inspect_ui(4242)["successo"])
        self.assertEqual(run.call_args.args[1]["JARVIS_UI_WINDOW_HANDLE"], "4242")

    @patch("desktop_intelligence._run")
    def test_set_value_targets_handle(self, run):
        run.return_value = {"success": True, "name": "Text Editor"}
        self.assertTrue(desktop_intelligence.ui_set_value("Text Editor", "hello", 4242)["successo"])
        self.assertEqual(run.call_args.args[1]["JARVIS_UI_WINDOW_HANDLE"], "4242")

    @patch("desktop_intelligence._run", side_effect=RuntimeError("token=secret-value"))
    def test_ui_errors_are_redacted(self, run):
        result = desktop_intelligence.ui_invoke("Save")
        self.assertFalse(result["successo"])
        self.assertNotIn("secret-value", result["errore"])
        self.assertIn("[REDACTED]", result["errore"])
