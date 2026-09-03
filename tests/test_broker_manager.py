import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from jarvis_broker.manager import BrokerManager, build_launch_spec
from jarvis_broker.protocol import BrokerResponse


class BrokerManagerTests(unittest.TestCase):
    def test_source_launch_uses_module_entrypoint_without_shell(self):
        spec = build_launch_spec()
        self.assertTrue(spec.executable.lower().endswith("python.exe"))
        self.assertEqual(spec.parameters, "-m jarvis_broker.server")

    def test_source_launch_passes_a_generated_pipe_as_an_argument(self):
        address = r"\\.\pipe\JarvisPrivilegedBroker_test"
        spec = build_launch_spec(address)
        self.assertIn("--address", spec.parameters)
        self.assertIn(address, spec.parameters)

    def test_source_launch_passes_loopback_port_without_shell(self):
        spec = build_launch_spec(tcp_port=54321)
        self.assertEqual(spec.parameters, "-m jarvis_broker.server --tcp-port 54321")

    def test_health_and_stop_use_authenticated_client(self):
        client = Mock()
        client.execute.return_value = BrokerResponse("id", True, "ok", {})
        manager = BrokerManager(client)
        self.assertTrue(manager.health())
        self.assertTrue(manager.stop(confirmed=True))
        self.assertEqual(client.execute.call_args_list[0].args, ("broker.ping", {}))
        self.assertEqual(client.execute.call_args_list[1].args, ("broker.stop", {}))

    def test_new_manager_does_not_probe_an_unassigned_endpoint(self):
        manager = BrokerManager()
        with patch.object(manager.client, "execute") as execute:
            self.assertFalse(manager.health())
        execute.assert_not_called()

    @patch("jarvis_broker.manager.os.name", "posix")
    def test_elevation_is_windows_only(self):
        self.assertFalse(BrokerManager(Mock()).start_elevated())

    def test_diagnostics_exposes_only_broker_lifecycle_status(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broker-startup.json").write_text(
                json.dumps({"stage": "failed", "error_type": "OSError"}), encoding="utf-8"
            )
            with patch("app_paths.data_path", return_value=root):
                self.assertEqual(BrokerManager.diagnostics()["stage"], "failed")


if __name__ == "__main__":
    unittest.main()
