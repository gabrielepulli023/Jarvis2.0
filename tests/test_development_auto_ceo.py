import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import permission_manager
from jarvis_core.runtime import RUNTIME as CORE_RUNTIME
from jarvis_skills import Capability, SkillManifest, SkillRegistry
from main import FULL_PROFILE_PERMISSIONS, startup_identity_check


class DevelopmentAutoCeoTests(unittest.TestCase):
    def setUp(self):
        permission_manager.clear_session()

    def tearDown(self):
        permission_manager.clear_session()

    def test_startup_session_is_authenticated_owner_ceo_and_never_guest(self):
        result = startup_identity_check()
        session = permission_manager.session_profile()

        self.assertEqual(session["name"], "OWNER")
        self.assertEqual(session["role"], "CEO")
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["method"], "development_auto_ceo")
        self.assertNotEqual(session["role"], "GUEST")
        self.assertEqual(session["permissions"], FULL_PROFILE_PERMISSIONS)
        self.assertEqual(result["status"], "authenticated")
        self.assertEqual(result["confidence"], 1.0)

    def test_network_permission_and_registered_skill_gate_are_allowed(self):
        startup_identity_check()
        session = permission_manager.session_profile()

        self.assertEqual(session["role"], "CEO")
        self.assertEqual(session["permissions"]["external_send"], "allow")
        self.assertEqual(permission_manager.decision("external_send"), "allow")
        self.assertTrue(CORE_RUNTIME.skills._authorize(Capability.NETWORK))

        with tempfile.TemporaryDirectory(prefix="jarvis_network_gate_") as folder:
            registry = SkillRegistry(Path(folder) / "metrics.db", CORE_RUNTIME.skills._authorize)
            registry.register(
                SkillManifest(
                    "test.network_gate",
                    "1.0.0",
                    "Network permission gate regression",
                    ("network gate",),
                    frozenset({Capability.NETWORK}),
                    "test:network_gate",
                ),
                lambda: {"success": True, "message": "gate passed"},
            )
            result = registry.execute("test.network_gate")

        self.assertTrue(result.success)
        self.assertEqual(result.message, "gate passed")

    def test_admin_confirm_reaches_capability_gate_without_becoming_denied(self):
        from jarvis_core.mode import RuntimeMode

        with patch.object(CORE_RUNTIME, "mode", RuntimeMode(safe=False)), patch(
            "jarvis_core.runtime.permission_decision", return_value="confirm"
        ):
            decision = CORE_RUNTIME.skills._authorize(Capability.SYSTEM_SETTINGS)
        self.assertEqual("confirm", decision)

    def test_admin_deny_reaches_capability_gate_as_denied(self):
        from jarvis_core.mode import RuntimeMode

        with patch.object(CORE_RUNTIME, "mode", RuntimeMode(safe=False)), patch(
            "jarvis_core.runtime.permission_decision", return_value="deny"
        ):
            decision = CORE_RUNTIME.skills._authorize(Capability.SYSTEM_SETTINGS)
        self.assertEqual("deny", decision)

    def test_permission_manager_keeps_admin_allow_confirm_and_deny_distinct(self):
        from jarvis_core.mode import RuntimeMode

        profile = {"mode": "assisted", "categories": {"admin": "allow"}}
        with patch.object(permission_manager, "_load", return_value=profile), patch(
            "jarvis_core.mode.RUNTIME_MODE", RuntimeMode(safe=False)
        ):
            self.assertEqual("confirm", permission_manager.decision("admin"))

        for configured in ("deny", "allow"):
            profile["categories"]["admin"] = configured
            with patch.object(permission_manager, "_load", return_value=profile), patch(
                "jarvis_core.mode.RUNTIME_MODE", RuntimeMode(safe=False)
            ):
                expected = "confirm" if configured == "allow" else "deny"
                self.assertEqual(expected, permission_manager.decision("admin"))


if __name__ == "__main__":
    unittest.main()
