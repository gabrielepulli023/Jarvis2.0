import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from decision_layer import decide
from jarvis_core.runtime import RUNTIME
from jarvis_expansion.routing import match_expansion_skill
from mission_control import verify_result


class _ReadbackQdrant:
    def __init__(self, *, readback=True):
        self.readback = readback
        self.points = {}

    def upload_collection(self, *, ids, payload, **_kwargs):
        self.points[str(ids[0])] = {"id": str(ids[0]), "payload": payload[0]}

    def retrieve(self, *, ids, **_kwargs):
        return [self.points[str(point_id)] for point_id in ids if self.readback and str(point_id) in self.points]

    def close(self):
        return None


class QdrantRoutingTests(unittest.TestCase):
    ADD = "Aggiungi memoria vettoriale con Qdrant: JARVIS_QDRANT_TEST_20260831, il colibrì viola custodisce 17 chiavi nella scatola numero 42."

    def test_natural_italian_forms_use_registered_expansion_intents(self):
        import main

        forms = {
            "Aggiungi memoria vettoriale con Qdrant: testo prova": "qdrant.add",
            "Salva questo in Qdrant: testo prova": "qdrant.add",
            "Memorizza con Qdrant testo prova": "qdrant.add",
            "Aggiungi alla memoria vettoriale Qdrant testo prova": "qdrant.add",
            "Usa Qdrant per memorizzare testo prova": "qdrant.add",
            "Cerca con Qdrant testo prova": "qdrant.search",
            "Cerca nella memoria vettoriale Qdrant testo prova": "qdrant.search",
            "Recupera da Qdrant testo prova": "qdrant.search",
        }
        for phrase, expected_skill in forms.items():
            match = match_expansion_skill(RUNTIME.skills, phrase)
            self.assertIsNotNone(match, phrase)
            self.assertEqual(expected_skill, match["skill"], phrase)
            self.assertTrue(main.deve_usare_router_operativo(phrase), phrase)
            self.assertTrue(decide(phrase).needs_tools, phrase)

    def test_deterministic_router_emits_expansion_call_for_add_and_search(self):
        import brain

        with patch.object(
            brain,
            "esegui_tool",
            return_value={
                "successo": True,
                "messaggio": "Operazione completata.",
                "verification": {"status": "verified", "strength": 1.0},
            },
        ) as execute:
            handled, message, _ = brain.interpreta_comando(self.ADD)
            self.assertTrue(handled)
            self.assertEqual("Memoria aggiunta a Qdrant.", message)
            add_call = execute.call_args.args
            self.assertEqual("expansion_call", add_call[0])
            self.assertEqual("qdrant.add", add_call[1]["skill"])
            self.assertIn("JARVIS_QDRANT_TEST_20260831", json.loads(add_call[1]["arguments_json"])["text"])

            handled, _message, _ = brain.interpreta_comando(
                "Cerca nella memoria vettoriale Qdrant JARVIS_QDRANT_TEST_20260831"
            )
            self.assertTrue(handled)
            search_call = execute.call_args.args
            self.assertEqual("expansion_call", search_call[0])
            self.assertEqual("qdrant.search", search_call[1]["skill"])
            self.assertEqual(
                "JARVIS_QDRANT_TEST_20260831",
                json.loads(search_call[1]["arguments_json"])["query"],
            )

    def test_deterministic_qdrant_path_exposes_standard_tool_diagnostics(self):
        import brain

        result = {
            "successo": True,
            "messaggio": "Operazione completata.",
            "skill": "qdrant.add",
            "dati": {
                "id": "point-1",
                "collection": "jarvis_expansion_memory",
                "verified": True,
                "verification_evidence": "read-back",
            },
            "verification": {"status": "verified", "strength": 1.0, "evidence": "read-back"},
        }
        output = StringIO()
        with patch.object(brain, "esegui_tool", return_value=result), redirect_stdout(output):
            handled, message, _ = brain.interpreta_comando(self.ADD)
        rendered = output.getvalue()
        self.assertTrue(handled)
        self.assertEqual("Memoria aggiunta a Qdrant.", message)
        self.assertIn("TOOL: expansion_call", rendered)
        self.assertIn("qdrant.add", rendered)
        self.assertIn("RISULTATO:", rendered)
        self.assertIn("'successo': True", rendered)

    def test_qdrant_search_returns_backend_payload_and_handles_no_hits(self):
        import brain

        payload = "JARVIS_QDRANT_MANUAL_TEST_2, un falco dorato conserva 31 gettoni dentro una valigia verde."
        result = {
            "successo": True,
            "messaggio": "Operazione completata.",
            "skill": "qdrant.search",
            "dati": {
                "collection": "jarvis_expansion_memory",
                "verified": True,
                "points": [{"id": "point-2", "score": 0.8123, "payload": {"text": payload}}],
            },
            "verification": {"status": "verified", "strength": 0.75, "evidence": "query"},
        }
        with patch.object(brain, "esegui_tool", return_value=result):
            handled, message, _ = brain.interpreta_comando("Cerca con Qdrant informazione su un volatile")
        self.assertTrue(handled)
        self.assertIn(payload, message)
        self.assertIn("score 0.8123", message)

        no_hits = dict(result)
        no_hits["dati"] = {"collection": "jarvis_expansion_memory", "verified": True, "points": []}
        with patch.object(brain, "esegui_tool", return_value=no_hits):
            handled, message, _ = brain.interpreta_comando("Cerca con Qdrant informazione inesistente")
        self.assertTrue(handled)
        self.assertEqual("Non ho trovato risultati in Qdrant.", message)

    def test_qdrant_search_payload_is_retained_in_operational_context(self):
        from jarvis_core.operational_context import OperationalContext

        payload = "un falco dorato conserva 31 gettoni dentro una valigia verde"
        context = OperationalContext()
        row = context.record(
            "expansion_call",
            {
                "successo": True,
                "skill": "qdrant.search",
                "dati": {
                    "verified": True,
                    "points": [{"payload": {"text": payload}, "score": 0.8}],
                },
                "verification": {"status": "verified"},
            },
            {"skill": "qdrant.search"},
        )
        self.assertEqual(payload, row["content"])
        self.assertEqual("verified", row["verification_status"])

    def test_existing_expansion_routes_remain_manifest_backed(self):
        import main

        forms = {
            "Converti file in markdown con MarkItDown": "documents.markitdown",
            "Analizza documento con Docling": "documents.docling",
            "Studia sito con Crawl4AI": "web.crawl4ai",
            "Cattura schermo veloce con DXcam": "screen.dxcam.capture",
        }
        for phrase, expected_skill in forms.items():
            match = match_expansion_skill(RUNTIME.skills, phrase)
            self.assertIsNotNone(match, phrase)
            self.assertEqual(expected_skill, match["skill"], phrase)
            self.assertTrue(main.deve_usare_router_operativo(phrase), phrase)

    def test_failed_qdrant_tool_cannot_become_a_successful_confirmation(self):
        import brain

        failed = {"successo": False, "messaggio": "Expansion sidecar non disponibile."}
        with patch.object(brain, "esegui_tool", return_value=failed):
            handled, message, _ = brain.interpreta_comando(self.ADD)
        self.assertTrue(handled)
        self.assertIn("non disponibile", message)
        self.assertNotRegex(message.casefold(), r"\b(?:memorizzato|registrato|archiviato|salvato)\b")

    def test_operational_qdrant_request_cannot_reach_conversational_ai(self):
        import main

        worker = main.JarvisWorker()
        with patch.object(main, "chiedi_jarvis") as chat, patch.object(worker, "parla_controllato") as speak:
            worker.risposta_ai(self.ADD)
        chat.assert_not_called()
        self.assertNotIn("memorizzato", str(speak.call_args).casefold())

    def test_common_operational_effect_verbs_require_a_tool_path(self):
        import main

        for phrase in (
            "Invia il messaggio di prova",
            "Modifica il documento di prova",
            "Genera il report di prova",
            "Riproduci il video di prova",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(decide(phrase).needs_tools)
                self.assertTrue(main.deve_usare_router_operativo(phrase))

    def test_successful_qdrant_tool_without_proof_is_not_confirmed(self):
        import brain

        with patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "Operazione completata."}):
            handled, message, _ = brain.interpreta_comando(self.ADD)
        self.assertTrue(handled)
        self.assertIn("Non posso confermare", message)

    def test_qdrant_verification_requires_backend_proof(self):
        unverified = verify_result(
            "expansion_call",
            {"skill": "qdrant.add"},
            {"successo": True, "skill": "qdrant.add", "dati": {"id": "x"}},
        )
        self.assertEqual("unverified", unverified["status"])
        verified = verify_result(
            "expansion_call",
            {"skill": "qdrant.add"},
            {
                "successo": True,
                "skill": "qdrant.add",
                "dati": {"id": "x", "verified": True, "verification_evidence": "readback"},
            },
        )
        self.assertEqual("verified", verified["status"])

    def test_qdrant_add_is_marked_verified_only_after_readback(self):
        from external_integrations.expansion.expansion_server import ExpansionEngine

        with tempfile.TemporaryDirectory(prefix="jarvis_qdrant_unit_") as folder:
            root = Path(folder)
            config = root / "config.json"
            config.write_text(json.dumps({"watchdog_enabled": False}), encoding="utf-8")
            engine = ExpansionEngine(config, root / "data")
            client = _ReadbackQdrant()
            with patch.object(engine, "_qdrant_client", return_value=client), patch.object(
                engine, "_qdrant_ensure_collection"
            ):
                result = engine.qdrant_add("testo con readback")
            self.assertTrue(result["verified"])
            self.assertEqual("jarvis_expansion_memory", result["collection"])
            engine.shutdown()

            failing_client = _ReadbackQdrant(readback=False)
            engine = ExpansionEngine(config, root / "data-failing")
            with patch.object(engine, "_qdrant_client", return_value=failing_client), patch.object(
                engine, "_qdrant_ensure_collection"
            ):
                with self.assertRaisesRegex(RuntimeError, "non ha restituito"):
                    engine.qdrant_add("testo senza readback")
            engine.shutdown()


if __name__ == "__main__":
    unittest.main()
