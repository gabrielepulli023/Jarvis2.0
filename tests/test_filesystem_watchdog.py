import tempfile
import threading
import time
import unittest
from pathlib import Path

from jarvis_core.events import EventBus
from jarvis_core.watchdog import FilesystemWatchRegistry


class FilesystemWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jarvis-watchdog-"))
        self.bus = EventBus()
        self.received = []
        self.bus.subscribe("watchdog.filesystem", self.received.append)
        self.notifications = []

        class Notifications:
            def notify(inner, *args, **kwargs):
                self.notifications.append((args, kwargs))

        self.registry = FilesystemWatchRegistry(self.bus, Notifications())

    def tearDown(self):
        self.registry.shutdown()
        for _ in range(10):
            try:
                import shutil
                shutil.rmtree(self.root)
                break
            except OSError:
                time.sleep(0.05)

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.03)
        return False

    def test_all_native_events_and_structured_notification(self):
        result = self.registry.start(str(self.root), events=["created", "modified", "moved", "deleted"], debounce_ms=20)
        self.assertTrue(result["success"])
        watch_id = result["data"]["watch_id"]
        source = self.root / "one.txt"
        source.write_text("one", encoding="utf-8")
        self.assertTrue(self.wait_for(lambda: any(e.payload["type"] == "created" for e in self.received)))
        source.write_text("two", encoding="utf-8")
        self.assertTrue(self.wait_for(lambda: any(e.payload["type"] == "modified" for e in self.received)))
        moved = self.root / "two.txt"
        source.rename(moved)
        self.assertTrue(self.wait_for(lambda: any(e.payload["type"] == "moved" for e in self.received)))
        moved.unlink()
        self.assertTrue(self.wait_for(lambda: any(e.payload["type"] == "deleted" for e in self.received)))
        self.assertTrue(all(e.payload["watch_id"] == watch_id for e in self.received))
        self.assertTrue(self.notifications)

    def test_duplicate_recursive_modes_and_invalid_directory(self):
        invalid = self.registry.start(str(self.root / "missing"), events=["created"])
        self.assertFalse(invalid["success"])
        first = self.registry.start(str(self.root), events=["created"], recursive=False)
        duplicate = self.registry.start(str(self.root), events=["created"], recursive=False)
        different = self.registry.start(str(self.root), events=["created"], recursive=True)
        self.assertTrue(first["success"])
        self.assertTrue(duplicate["data"]["duplicate"])
        self.assertTrue(different["success"])
        self.assertEqual(len(self.registry.list()), 2)

    def test_debounce_filters_stop_and_shutdown_are_clean(self):
        self.registry.start(str(self.root), events=["modified"], debounce_ms=500)
        path = self.root / "file.txt"
        path.write_text("a", encoding="utf-8")
        self.assertTrue(self.wait_for(lambda: self.received))
        baseline = len(self.received)
        for value in ("b", "c", "d"):
            path.write_text(value, encoding="utf-8")
        time.sleep(0.15)
        self.assertEqual(len(self.received), baseline)
        self.assertTrue(self.registry.stop_all()["success"])
        self.assertFalse(self.registry.list())
        self.registry.shutdown()
        self.assertTrue(all(not getattr(w.observer, "is_alive", lambda: False)() for w in []))

    def test_runtime_routes_natural_language_and_preserves_windows_path(self):
        from unittest.mock import patch
        import brain
        class Result:
            success = True
            message = "ok"
            data = {}
        with patch.object(brain.CORE_RUNTIME.skills, "execute", return_value=Result()) as execute:
            outcome = brain._interpreta_comando_locale(
                r"Monitora la cartella C:\Users\gabri\Desktop\JARVIS_WATCHDOG_TEST e avvisami quando viene creato o modificato un file."
            )
        self.assertEqual(outcome[0], True)
        execute.assert_called_once_with(
            "watchdog.start",
            path=r"C:\Users\gabri\Desktop\JARVIS_WATCHDOG_TEST",
            events=["created", "modified"],
            recursive=False,
        )

    def test_runtime_routes_list_and_stop_all_commands(self):
        from unittest.mock import patch
        import brain
        class Result:
            success = True
            message = "ok"
            data = {"watchers": []}
        with patch.object(brain.CORE_RUNTIME.skills, "execute", return_value=Result()) as execute:
            brain._interpreta_comando_locale("Quali cartelle stai monitorando?")
            brain._interpreta_comando_locale("Ferma tutti i monitoraggi")
        self.assertEqual(execute.call_args_list[0].args, ("watchdog.list",))
        self.assertEqual(execute.call_args_list[1].kwargs, {"all_watchers": True})


if __name__ == "__main__":
    unittest.main()
