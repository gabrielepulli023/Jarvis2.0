import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jarvis_core.operational_context import OperationalContext
from jarvis_core.operational_followup import execute, is_operational_followup
from jarvis_expansion.routing import match_expansion_skill, secrets_arguments
from jarvis_skills import Capability, SkillManifest, SkillRegistry


class KeyringRoutingTests(unittest.TestCase):
    REQUEST = (
        'Salva nel Keyring di Windows il segreto "JARVIS_SECRET_7391" '
        'con servizio "JARVIS_KEYRING_TEST" e username "test_user".'
    )
    SECRET = "JARVIS_SECRET_7391"

    def test_complete_keyring_request_uses_registered_expansion_skill(self):
        import main
        from jarvis_core.runtime import RUNTIME

        match = match_expansion_skill(RUNTIME.skills, self.REQUEST)
        self.assertIsNotNone(match)
        self.assertEqual("secrets.store", match["skill"])
        self.assertEqual(
            {
                "service": "JARVIS_KEYRING_TEST",
                "username": "test_user",
                "secret": self.SECRET,
            },
            secrets_arguments("secrets.store", self.REQUEST),
        )
        self.assertTrue(main.deve_usare_router_operativo(self.REQUEST))
        self.assertFalse(is_operational_followup(self.REQUEST))

    def test_deterministic_keyring_route_emits_expansion_call_with_original_arguments(self):
        import brain

        with patch.object(
            brain,
            "esegui_tool",
            return_value={
                "successo": False,
                "richiede_conferma": True,
                "messaggio": "Conferma utente richiesta.",
                "azione_id": "keyring-action",
            },
        ) as execute_tool:
            handled, message, _ = brain.interpreta_comando(self.REQUEST)

        self.assertTrue(handled)
        self.assertIn("conferma", message.casefold())
        self.assertEqual("expansion_call", execute_tool.call_args.args[0])
        payload = execute_tool.call_args.args[1]
        self.assertEqual("secrets.store", payload["skill"])
        self.assertEqual(
            {
                "service": "JARVIS_KEYRING_TEST",
                "username": "test_user",
                "secret": self.SECRET,
            },
            json.loads(payload["arguments_json"]),
        )

    def test_keyring_confirmation_is_single_pending_and_executes_original_secret(self):
        import brain
        import main

        calls = []
        with tempfile.TemporaryDirectory(prefix="jarvis_keyring_routing_") as folder:
            registry = SkillRegistry(
                Path(folder) / "metrics.db",
                lambda _capability: True,
                lambda manifest, _arguments=None: "confirm" if manifest.name == "secrets.store" else "allow",
            )
            registry.register(
                SkillManifest(
                    "secrets.store",
                    "1",
                    "Store a secret",
                    ("salva segreto", "salva nel keyring"),
                    frozenset({Capability.SYSTEM_SETTINGS}),
                    "jarvis_expansion:keyring_store",
                    risk="sensitive",
                ),
                lambda **arguments: (
                    calls.append(dict(arguments))
                    or {
                        "success": True,
                        "message": "Segreto memorizzato.",
                        "data": {"stored": True, "service": arguments["service"], "username": arguments["username"]},
                    }
                ),
            )
            brain.CORE_RUNTIME.context.operational.clear()
            try:
                with patch.object(brain.CORE_RUNTIME, "skills", registry), patch.object(
                    brain, "pending_action_guard", return_value={}
                ), patch.object(brain, "permission_profile", return_value={"pin": False}):
                    handled, message, _ = brain.interpreta_comando(self.REQUEST)
                    self.assertTrue(handled)
                    self.assertIn("conferma", message.casefold())
                    self.assertEqual(1, len(registry.pending()))
                    stored_context = brain.CORE_RUNTIME.context.operational_context()
                    self.assertNotIn(self.SECRET, json.dumps(stored_context, ensure_ascii=False))
                    action_id = next(iter(registry.pending()))

                    worker = main.JarvisWorker()
                    with patch.object(brain, "pending_confirmation_actions", return_value=[{"action_id": action_id}]), patch.object(
                        worker, "_risposta_locale"
                    ) as reply:
                        self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))

                self.assertEqual(
                    [{"service": "JARVIS_KEYRING_TEST", "username": "test_user", "secret": self.SECRET}],
                    calls,
                )
                self.assertEqual({}, registry.pending())
                self.assertNotIn(self.SECRET, str(reply.call_args))
            finally:
                brain.CORE_RUNTIME.context.operational.clear()

    def test_delete_wording_variants_route_to_secrets_delete_with_labeled_arguments(self):
        import main
        from jarvis_core.runtime import RUNTIME

        requests = (
            'Elimina dal Keyring di Windows la credenziale con servizio "X" e username "Y".',
            'Cancella la credenziale con servizio "X" e username "Y".',
            'Rimuovi dal credential manager la credenziale con servizio "X" e username "Y".',
            'Elimina password dal credential manager con servizio "X" e username "Y".',
            'Rimuovi token dal gestore credenziali con servizio "X" e username "Y".',
            'Cancella api key dal keyring con servizio "X" e username "Y".',
        )
        for request in requests:
            match = match_expansion_skill(RUNTIME.skills, request)
            self.assertIsNotNone(match, request)
            self.assertEqual("secrets.delete", match["skill"], request)
            self.assertEqual({"service": "X", "username": "Y"}, secrets_arguments("secrets.delete", request))
            self.assertTrue(main.deve_usare_router_operativo(request), request)

    def test_delete_confirmation_is_single_pending_and_executes_original_keyring_delete(self):
        import brain
        import main

        calls = []
        with tempfile.TemporaryDirectory(prefix="jarvis_keyring_delete_") as folder:
            registry = SkillRegistry(
                Path(folder) / "metrics.db", lambda _capability: True,
                lambda manifest, _arguments=None: "confirm" if manifest.name == "secrets.delete" else "allow",
            )
            registry.register(
                SkillManifest(
                    "secrets.delete", "1", "Delete a secret", ("elimina dal keyring",),
                    frozenset({Capability.SYSTEM_SETTINGS}), "jarvis_expansion:keyring_delete", risk="sensitive",
                ),
                lambda **arguments: calls.append(dict(arguments)) or {"success": True, "message": "Credenziale eliminata."},
            )
            request = 'Elimina dal Keyring la credenziale con servizio "X" e username "Y".'
            brain.CORE_RUNTIME.context.operational.clear()
            try:
                with patch.object(brain.CORE_RUNTIME, "skills", registry), patch.object(
                    brain, "pending_action_guard", return_value={}
                ), patch.object(brain, "permission_profile", return_value={"pin": False}):
                    handled, message, _ = brain.interpreta_comando(request)
                    self.assertTrue(handled)
                    self.assertIn("conferma", message.casefold())
                    self.assertEqual(1, len(registry.pending()))
                    action_id = next(iter(registry.pending()))
                    worker = main.JarvisWorker()
                    with patch.object(brain, "pending_confirmation_actions", return_value=[{"action_id": action_id}]), patch.object(
                        worker, "_risposta_locale"
                    ):
                        self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))
                self.assertEqual([{"service": "X", "username": "Y"}], calls)
                self.assertEqual({}, registry.pending())
            finally:
                brain.CORE_RUNTIME.context.operational.clear()

    def test_incomplete_delete_does_not_invent_service_or_username(self):
        from jarvis_core.runtime import RUNTIME

        request = "Elimina la credenziale dal Keyring."
        self.assertEqual("secrets.delete", match_expansion_skill(RUNTIME.skills, request)["skill"])
        self.assertIsNone(secrets_arguments("secrets.delete", request))

    def test_delete_cancellation_consumes_pending_without_calling_keyring(self):
        calls = []
        with tempfile.TemporaryDirectory(prefix="jarvis_keyring_delete_cancel_") as folder:
            registry = SkillRegistry(
                Path(folder) / "metrics.db", lambda _capability: True,
                lambda _manifest, _arguments=None: "confirm",
            )
            registry.register(
                SkillManifest(
                    "secrets.delete", "1", "Delete a secret", ("elimina dal keyring",),
                    frozenset({Capability.SYSTEM_SETTINGS}), "jarvis_expansion:keyring_delete", risk="sensitive",
                ),
                lambda **arguments: calls.append(arguments) or {"success": True},
            )
            staged = registry.execute("secrets.delete", service="X", username="Y")
            self.assertTrue(staged.data["requires_confirmation"])
            self.assertIsNotNone(registry.cancel(staged.data["action_id"]))
            self.assertEqual([], calls)
            self.assertEqual({}, registry.pending())

    def test_save_that_without_context_reports_missing_context_but_explicit_secret_does_not(self):
        import main

        def writer(_path, _content):
            return {"successo": True}

        def opener(_path, _application):
            return {"successo": True}

        handled, message, result = execute(
            "salva quello",
            None,
            writer=writer,
            opener=opener,
        )
        self.assertTrue(handled)
        self.assertFalse(result["successo"])
        self.assertIn("risultato operativo", message.casefold())
        self.assertFalse(is_operational_followup("salva questo segreto nel keyring con servizio X e username Y"))
        self.assertTrue(main.deve_usare_router_operativo("salva questo segreto nel keyring con servizio X e username Y"))

    def test_secret_is_redacted_from_diagnostics_audit_and_operational_context(self):
        import audit_log
        import brain
        from jarvis_core.logging import redact

        arguments = {
            "skill": "secrets.store",
            "arguments_json": json.dumps(
                {"service": "JARVIS_KEYRING_TEST", "username": "test_user", "secret": self.SECRET}
            ),
        }
        output = StringIO()
        with redirect_stdout(output):
            brain._stampa_tool_inizio("expansion_call", arguments)
        rendered = output.getvalue()
        self.assertNotIn(self.SECRET, rendered)
        self.assertIn("***REDACTED***", rendered)

        context = OperationalContext()
        row = context.record(
            "expansion_call",
            {"successo": False, "richiede_conferma": True, "azione_id": "a1", "rischio": "sensitive"},
            arguments,
        )
        self.assertNotIn(self.SECRET, json.dumps(row, ensure_ascii=False))
        self.assertEqual(
            self.SECRET,
            json.loads(arguments["arguments_json"])["secret"],
        )
        self.assertEqual(
            "***REDACTED***",
            json.loads(row["pending_action"]["arguments"]["arguments_json"])["secret"],
        )
        self.assertNotIn(self.SECRET, redact(arguments))

        with tempfile.TemporaryDirectory(prefix="jarvis_keyring_audit_") as folder:
            audit_path = Path(folder) / "audit.jsonl"
            with patch.object(audit_log, "LOG_PATH", audit_path):
                audit_log.record("tool_started", arguments=arguments)
            self.assertNotIn(self.SECRET, audit_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
