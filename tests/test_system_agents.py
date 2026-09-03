import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pyperclip
from jarvis_core.events import EventBus
from jarvis_system import ClipboardManager, NetworkAgent, NotificationCenter, SystemInformation


class NetworkAgentTests(unittest.TestCase):
    def test_system_information_exposes_gpu_probe_result(self):
        result = SystemInformation(gpu_probe=lambda: {"available": True, "devices": [{"name": "GPU"}]}).snapshot()
        self.assertTrue(result["gpu"]["available"])

    def test_adapters_are_structured(self):
        rows = NetworkAgent().adapters()
        self.assertIsInstance(rows, list)
        if rows:
            self.assertTrue({"name", "up", "addresses"} <= rows[0].keys())

    def test_invalid_ping_host_never_reaches_subprocess(self):
        with patch("jarvis_system.network.subprocess.run") as run:
            with self.assertRaises(ValueError):
                NetworkAgent().ping("host & shutdown")
        run.assert_not_called()

    def test_connectivity_failure_is_structured(self):
        with patch("jarvis_system.network.socket.create_connection", side_effect=OSError("offline")):
            result = NetworkAgent().connectivity()
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "OSError")

    def test_dns_failure_redacts_provider_details(self):
        with patch("jarvis_system.network.socket.getaddrinfo", side_effect=OSError("api_key=secret")):
            result = NetworkAgent().dns("example.com")
            self.assertNotIn("secret", result["error"])


class ClipboardAndNotificationTests(unittest.TestCase):
    def test_clipboard_is_on_demand_and_bounded(self):
        manager = ClipboardManager([])
        with (
            patch("jarvis_system.clipboard.ImageGrab.grabclipboard", return_value=None),
            patch("jarvis_system.clipboard.pyperclip.paste", return_value="abcdef"),
        ):
            result = manager.inspect(3)
            self.assertEqual(result["text"], "abc")
            self.assertTrue(result["truncated"])

    def test_clipboard_failure_redacts_provider_details(self):
        manager = ClipboardManager([])
        with patch("jarvis_system.clipboard.pyperclip.paste", side_effect=pyperclip.PyperclipException("token=secret")):
            result = manager.inspect()
            self.assertNotIn("secret", result["error"])

    def test_image_save_is_confined(self):
        root = Path(tempfile.mkdtemp())
        manager = ClipboardManager([root])
        image = Image.new("RGB", (2, 2))
        with patch("jarvis_system.clipboard.ImageGrab.grabclipboard", return_value=image):
            self.assertFalse(manager.save_image(str(root.parent / "escape.png"))["success"])
            self.assertTrue(manager.save_image(str(root / "ok.png"))["success"])

    def test_notification_is_bounded_and_emits_event(self):
        bus = EventBus()
        events = []
        bus.subscribe("notification.created", events.append)
        center = NotificationCenter(bus, limit=10)
        for index in range(20):
            center.notify("x", str(index))
        self.assertEqual(len(center.snapshot()), 10)
        self.assertEqual(len(events), 20)


if __name__ == "__main__":
    unittest.main()
