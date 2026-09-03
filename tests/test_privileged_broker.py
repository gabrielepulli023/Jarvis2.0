import unittest
from dataclasses import replace
from unittest.mock import patch

from jarvis_broker.protocol import BrokerProtocol
from jarvis_broker.server import execute


class PrivilegedBrokerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.secret = b"x" * 32
        self.seen = set()

    def test_valid_confirmed_admin_request(self):
        request = BrokerProtocol.create(
            self.secret, "user", "winget.install", {"package_id": "Git.Git"}, user_confirmation=True, now=100
        )
        BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=self.seen, now=100)
        self.assertIn(request.request_id, self.seen)

    def test_admin_request_without_confirmation_is_rejected(self):
        request = BrokerProtocol.create(self.secret, "user", "winget.install", {"package_id": "Git.Git"}, now=100)
        with self.assertRaises(PermissionError):
            BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=self.seen, now=100)

    def test_tampering_replay_expiry_and_unknown_action_are_rejected(self):
        request = BrokerProtocol.create(self.secret, "user", "system.info", {}, now=100)
        with self.assertRaises(PermissionError):
            BrokerProtocol.validate(
                replace(request, parameters={"tampered": True}),
                self.secret,
                expected_caller="user",
                seen=set(),
                now=100,
            )
        BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=self.seen, now=100)
        with self.assertRaises(ValueError):
            BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=self.seen, now=100)
        expired = BrokerProtocol.create(self.secret, "user", "system.info", {}, now=1)
        with self.assertRaises(ValueError):
            BrokerProtocol.validate(expired, self.secret, expected_caller="user", seen=set(), now=100)
        with self.assertRaises(ValueError):
            BrokerProtocol.create(self.secret, "user", "arbitrary.shell", {}, now=100)

    def test_mutating_system_actions_require_confirmation(self):
        for action in ("firewall.profile", "task.disable", "driver.scan", "windows_update.scan", "winget.upgrade_all"):
            request = BrokerProtocol.create(self.secret, "user", action, {}, now=100)
            with self.assertRaises(PermissionError):
                BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=set(), now=100)

    @patch("jarvis_broker.server._run")
    def test_driver_update_and_firewall_commands_are_fixed_argv(self, run):
        run.return_value = {"exit_code": 0}
        execute("driver.list", {})
        self.assertEqual(run.call_args.args[0], ["pnputil.exe", "/enum-drivers"])
        execute("firewall.profile", {"profile": "privateprofile", "enabled": True})
        self.assertEqual(run.call_args.args[0], ["netsh", "advfirewall", "set", "privateprofile", "state", "on"])
        with self.assertRaises(ValueError):
            execute("task.disable", {"task_name": "bad\n/DELETE"})

    @patch("jarvis_broker.server._run")
    def test_inventory_queries_use_fixed_powershell_argv(self, run):
        run.return_value = {"exit_code": 0}
        for action in ("system.info", "software.list"):
            request = BrokerProtocol.create(self.secret, "user", action, {}, now=100)
            BrokerProtocol.validate(request, self.secret, expected_caller="user", seen=set(), now=100)
            execute(action, {})
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])


if __name__ == "__main__":
    unittest.main()
