import sys
import unittest
from unittest.mock import patch
from jarvis_apps import AppManager, AppRecord
from jarvis_broker.protocol import BrokerResponse
from jarvis_core.events import EventBus
from jarvis_core.processes import ProcessManager
from jarvis_windows import WindowInfo


class FakeClient:
    def __init__(self):
        self.calls = []

    def execute(self, action, parameters, confirmed=False):
        self.calls.append((action, parameters, confirmed))
        return BrokerResponse("id", True, "ok", {"stdout": "candidate"})


class FakeBroker:
    def __init__(self):
        self.client = FakeClient()


class ProcessManagerExpandedTests(unittest.TestCase):
    def test_running_inventory_snapshot_reports_truncation(self):
        manager = ProcessManager(EventBus())

        class Process:
            def __init__(self, pid):
                self.info = {"pid": pid, "name": f"app{pid}.exe", "exe": None}

        with patch("jarvis_core.processes.psutil.process_iter", return_value=[Process(1), Process(2), Process(3)]):
            partial = manager.running_inventory_snapshot(2)
        self.assertEqual(len(partial["processes"]), 2)
        self.assertFalse(partial["complete"])
        manager.shutdown()

    def test_inventory_exposes_resource_and_hierarchy_fields(self):
        manager = ProcessManager(EventBus())
        rows = manager.inventory(10)
        self.assertTrue(rows)
        self.assertTrue({"pid", "ppid", "name", "status", "cpu_percent", "memory_bytes", "children"} <= rows[0].keys())
        manager.shutdown()

    def test_restart_preserves_command_and_kill_tree_is_owned_only(self):
        manager = ProcessManager(EventBus())
        item = manager.start([sys.executable, "-c", "import time;time.sleep(5)"])
        restarted = manager.restart(item.id)
        self.assertIsNotNone(restarted)
        self.assertEqual(restarted.command, item.command)
        self.assertEqual(manager.kill_tree("not-owned"), 0)
        self.assertGreaterEqual(manager.kill_tree(restarted.id), 1)
        manager.shutdown()


class AppManagerTests(unittest.TestCase):
    def setUp(self):
        self.broker = FakeBroker()
        self.manager = AppManager(self.broker, ProcessManager(EventBus()))

    def tearDown(self):
        self.manager.processes.shutdown()

    def test_resolution_refuses_ambiguous_name(self):
        apps = [AppRecord("Visual Studio"), AppRecord("Visual Studio Code")]
        with patch.object(self.manager, "discover", return_value=apps):
            result = self.manager.resolve("visual")
            self.assertTrue(result.ambiguous)
            self.assertIsNone(result.exact)

    def test_exact_package_mutations_use_confirmed_broker_request(self):
        result = self.manager.package_action("install", "VideoLAN.VLC")
        self.assertTrue(result["success"])
        self.assertEqual(self.broker.client.calls, [("winget.install", {"package_id": "VideoLAN.VLC"}, True)])

    def test_package_search_is_non_elevating_and_structured(self):
        self.assertTrue(self.manager.packages("Blender")["success"])
        self.assertFalse(self.broker.client.calls[0][2])

    def test_close_uses_window_message_not_process_termination(self):
        class Window:
            handle = 7

        class Backend:
            def __init__(self):
                self.calls = []

            def close(self, handle):
                self.calls.append(handle)
                return True

        class Windows:
            def __init__(self):
                self.backend = Backend()
                self.count = 0

            def find(self, query):
                self.count += 1
                return [Window()] if self.count == 1 else []

        windows = Windows()
        manager = AppManager(self.broker, self.manager.processes, windows)
        result = manager.close("Editor", 0.2)
        self.assertTrue(result["success"])
        self.assertEqual(windows.backend.calls, [7])

    def test_close_except_preserves_allowlist_and_jarvis(self):
        rows = [
            WindowInfo(1, "VS Code", 1, "Code.exe", 0, 0, 1, 1, 0, "normal", False),
            WindowInfo(2, "Discord", 2, "Discord.exe", 0, 0, 1, 1, 0, "normal", False),
            WindowInfo(3, "JARVIS", 3, "JARVIS.exe", 0, 0, 1, 1, 0, "normal", False),
        ]

        class Backend:
            def __init__(self):
                self.closed = []

            def list_windows(self):
                return [row for row in rows if row.handle not in self.closed]

            def close(self, handle):
                self.closed.append(handle)
                return True

        class Windows:
            def __init__(self):
                self.backend = Backend()

        windows = Windows()
        manager = AppManager(self.broker, self.manager.processes, windows)
        result = manager.close_except(["VS Code"], 0.2)
        self.assertTrue(result["success"])
        self.assertEqual(windows.backend.closed, [2])
        self.assertEqual(result["data"]["kept"], [1, 3])


if __name__ == "__main__":
    unittest.main()
