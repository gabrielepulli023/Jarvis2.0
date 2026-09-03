import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.local_services import LocalServicesManager


class FakeProcesses:
    def __init__(self):
        self.started = []
        self.killed = []

    def start(self, command, **kwargs):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        item = SimpleNamespace(id="owned-id", process=proc)
        self.started.append(item)
        return item

    def snapshot(self):
        return [{"id": item.id, "running": item.process.poll() is None} for item in self.started]

    def kill_tree(self, process_id, timeout=3.0):
        self.killed.append(process_id)
        for item in self.started:
            if item.id == process_id and item.process.poll() is None:
                item.process.kill()
        return 1


class LocalServicesTests(unittest.TestCase):
    def setUp(self):
        self.processes = FakeProcesses()
        self.manager = LocalServicesManager(self.processes, request=lambda *_args: {"data": [{"id": "model"}]})
        self._openhands_patcher = patch.object(self.manager, "_start_openhands")
        self._openhands_start = self._openhands_patcher.start()

    def tearDown(self):
        self._openhands_patcher.stop()
        self.manager.stop()

    def test_openhands_existing_running_is_external(self):
        self._openhands_patcher.stop()
        with patch.object(self.manager, "_openhands_container", return_value=(True, True, False)), \
             patch.object(self.manager, "_openhands_probe", return_value=True):
            self.manager._start_openhands()
        self.assertEqual(self.manager.services["openhands"].ownership, "external")
        with patch.object(self.manager, "_docker") as docker:
            self.manager._stop_one("openhands")
            docker.assert_not_called()

    def test_openhands_absent_is_created_and_owned(self):
        self._openhands_patcher.stop()
        with patch.object(self.manager, "_openhands_container", return_value=(False, False, False)), \
             patch.object(self.manager, "_openhands_probe", side_effect=[False, True]), \
             patch.object(self.manager, "_docker", return_value=(0, "", "")) as docker:
            self.manager._start_openhands()
        self.assertEqual(self.manager.services["openhands"].ownership, "jarvis")
        self.assertEqual(self.manager.services["openhands"].state, "ready")
        run_args = docker.call_args.args[0]
        self.assertIn("openhands-jarvis", run_args)
        self.assertIn("--restart=no", run_args)
        self.assertIn("-v", run_args)

    def test_openhands_stopped_container_is_owned_when_session_starts_it(self):
        self._openhands_patcher.stop()
        with patch.object(self.manager, "_openhands_container", return_value=(True, False, False)), \
             patch.object(self.manager, "_openhands_probe", return_value=True), \
             patch.object(self.manager, "_docker", return_value=(0, "", "")):
            self.manager._start_openhands()
        self.assertEqual(self.manager.services["openhands"].ownership, "jarvis")
        with patch.object(self.manager, "_docker") as docker:
            self.manager.stop()
            docker.assert_called_once_with(("stop", "openhands-jarvis"), timeout=10.0)

    def test_shutdown_service_error_does_not_block_other_services(self):
        with patch.object(self.manager, "_stop_one", side_effect=[RuntimeError("screen"), None, None]) as stop_one:
            self.manager.stop()
        self.assertEqual(stop_one.call_count, 3)

    def test_openhands_readiness_timeout_stops_owned_container(self):
        self._openhands_patcher.stop()
        with patch.object(self.manager, "_openhands_container", return_value=(False, False, False)), \
             patch.object(self.manager, "_openhands_probe", return_value=False), \
             patch.object(self.manager, "_docker", return_value=(0, "", "")) as docker, \
             patch("jarvis_core.local_services.time.monotonic", side_effect=[0, 0, 100]):
            self.manager._start_openhands()
        self.assertEqual(self.manager.services["openhands"].state, "failed")
        self.assertIn(("stop", "openhands-jarvis"), [call.args[0] for call in docker.call_args_list])

    @patch("jarvis_core.local_services.shutil.which", return_value=None)
    def test_openhands_degrades_when_wsl_is_unavailable(self, _which):
        self.assertEqual(self.manager._docker(("ps",))[0], 127)

    @patch.object(LocalServicesManager, "_docker", return_value=(127, "", "docker unavailable"))
    def test_openhands_degrades_when_docker_is_unavailable(self, _docker):
        self._openhands_patcher.stop()
        with patch.object(self.manager, "_openhands_container", return_value=(False, False, False)):
            self.manager._start_openhands()
        self.assertEqual(self.manager.services["openhands"].state, "failed")

    @patch("jarvis_core.local_services.LocalServicesManager._command", return_value=(sys.executable, "-c", ""))
    def test_external_services_are_reused_and_not_killed(self, _command):
        self.manager.start()
        self.assertEqual(self.manager.services["screenpipe"].ownership, "external")
        self.assertEqual(self.manager.services["llama_cpp"].ownership, "external")
        self.manager.stop()
        self.assertEqual(self.processes.killed, [])

    @patch("jarvis_core.local_services.LocalServicesManager._ready", side_effect=[False, True, False, True])
    @patch("jarvis_core.local_services.LocalServicesManager._command", return_value=(sys.executable, "-c", ""))
    def test_started_services_are_owned_and_killed(self, _command, _ready):
        self.manager.start()
        self.assertEqual(self.manager.services["screenpipe"].ownership, "jarvis")
        self.assertEqual(self.manager.services["llama_cpp"].ownership, "jarvis")
        self.manager.stop()
        self.assertEqual(self.processes.killed, ["owned-id", "owned-id"])
        self.manager.stop()

    @patch("jarvis_core.local_services.LocalServicesManager._ready", return_value=False)
    @patch("jarvis_core.local_services.LocalServicesManager._command", return_value=None)
    def test_missing_executable_fails_without_crashing_runtime(self, _command, _ready):
        self.manager.start()
        self.assertEqual(self.manager.services["screenpipe"].state, "failed")
        self.assertEqual(self.manager.services["llama_cpp"].state, "failed")

    def test_llama_probe_rejects_empty_models(self):
        self.manager._request = lambda *_args: {"data": []}
        self.assertFalse(self.manager._llama_probe())


if __name__ == "__main__":
    unittest.main()
