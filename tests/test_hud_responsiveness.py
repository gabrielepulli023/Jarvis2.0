import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hud import ActivitySurface, CommandCenterSurface


class HUDResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_log_batches_entries_without_rendering_each_one(self):
        surface = ActivitySurface()
        calls = []
        surface._render_entries = lambda *_: calls.append(True)
        for index in range(500):
            surface.add_entry("SISTEMA", "TEST", f"row {index}")
        self.app.processEvents()
        self.assertLessEqual(len(calls), 20)
        self.assertEqual(len(surface.entries), 500)
        surface.close()

    def test_command_center_refresh_returns_before_slow_snapshot(self):
        surface = CommandCenterSurface()
        surface._value = lambda _category: {"initial": True}
        surface.show()
        deadline = time.monotonic() + 1.0
        while surface._refresh_inflight and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        surface._value = lambda _category: (time.sleep(0.25) or {"ok": True})
        started = time.perf_counter()
        surface.refresh()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.05)
        deadline = time.monotonic() + 1.0
        while surface._refresh_inflight and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(surface._refresh_inflight)
        self.assertIn('"ok": true', surface.content.toPlainText())
        surface.close()


if __name__ == "__main__":
    unittest.main()
