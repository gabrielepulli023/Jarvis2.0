import tempfile
import unittest
from pathlib import Path

from jarvis_core.orchestrator import AutonomousOrchestrator
from jarvis_core.response_renderer import ResponseRenderer, TechnicalResult
from jarvis_skills import Capability, SkillManifest, SkillRegistry, SkillResult


class _State:
    def __init__(self):
        self.values = {}

    def set(self, key, value, source=None):
        self.values[key] = {"value": value, "source": source}


class ResponseRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = ResponseRenderer()

    def test_url_is_displayed_but_not_spoken(self):
        result = self.renderer.render(
            TechnicalResult(True, "Ho trovato https://github.com/OpenHands/OpenHands"),
            request="cerca il progetto OpenHands",
        )
        self.assertIn("https://github.com/OpenHands/OpenHands", result.display_response)
        self.assertNotIn("https://", result.spoken_response)
        self.assertIn("GitHub", result.spoken_response)

    def test_path_is_abbreviated_in_speech_and_kept_on_hud(self):
        path = r"C:\Users\gabri\Desktop\Jarvis2.0\reports\report.txt"
        result = self.renderer.render(TechnicalResult(True, f"Report salvato in {path}"))
        self.assertIn(path, result.display_response)
        self.assertNotIn(path, result.spoken_response)
        self.assertIn("reports", result.spoken_response)

    def test_tool_name_and_technical_error_are_naturalized(self):
        success = self.renderer.render(TechnicalResult(True, "Ho usato searxng.search."))
        failure = self.renderer.render(TechnicalResult(False, "ConnectionError: HTTP 503 da expansion_call."))
        self.assertNotIn("searxng.search", success.spoken_response)
        self.assertIn("cercato sul web", success.spoken_response)
        self.assertEqual("Quel servizio al momento non risponde.", failure.spoken_response)

    def test_technical_mode_keeps_details_and_unverified_never_says_done(self):
        url = "https://example.test/report"
        technical = self.renderer.render(
            TechnicalResult(
                False,
                f"HTTP 404 su {url}",
                error="HTTP 404",
                technical_details={"request_id": "abc123"},
            ),
            request="modalità tecnica",
        )
        unverified = self.renderer.render(
            TechnicalResult(True, "Scrittura eseguita", verification_status="unverified")
        )
        self.assertIn("HTTP 404", technical.spoken_response)
        self.assertIn(url, technical.display_response)
        self.assertIn("abc123", technical.display_response)
        self.assertNotIn("Fatto", unverified.spoken_response)
        self.assertIn("verificare", unverified.spoken_response)

    def test_link_request_is_silent_and_explicit_url_request_is_allowed(self):
        url = "https://github.com/microsoft/JARVIS"
        link = self.renderer.render(TechnicalResult(True, f"Ho trovato {url}"), request="mandami il link")
        full = self.renderer.render(TechnicalResult(True, url), request="dimmi l'URL completo")
        self.assertIn("messo a schermo", link.spoken_response)
        self.assertNotIn("https://", link.spoken_response)
        self.assertIn(url, full.spoken_response)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.allowed = {Capability.READ_FILES}
        self.registry = SkillRegistry(self.root / "skills.db", lambda capability: capability in self.allowed)
        self.state = _State()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def test_catalog_trace_and_dynamic_recovery_use_registry(self):
        self.registry.register(
            SkillManifest(
                "primary", "1", "Primary web search", ("cerca",), frozenset({Capability.READ_FILES}), "searx:search",
                fallbacks=("backup",), retries=1,
            ),
            lambda: SkillResult(False, "ConnectionError", skill="primary"),
        )
        self.registry.register(
            SkillManifest("backup", "1", "Offline search", ("backup",), frozenset({Capability.READ_FILES}), "local:search"),
            lambda: SkillResult(True, "Risultati", {"verified": True}, "backup"),
        )
        orchestrator = AutonomousOrchestrator(self.registry, self.state)
        catalog = orchestrator.capability_catalog("cerca sul web")
        primary = next(row for row in catalog if row["name"] == "primary")
        self.assertEqual("web_search", primary["capability"])
        self.assertIn("verification", primary["outputs"])
        run_id = orchestrator.begin("cerca e verifica", {"steps": []})
        failed = orchestrator.observe(run_id, "primary", {}, {"success": False, "message": "timeout"})
        self.assertEqual("retry_or_fallback", failed["recovery"]["action"])
        result = self.registry.execute("primary")
        self.assertTrue(result.success)
        self.assertEqual("backup", result.skill)
        observed = orchestrator.observe(run_id, "primary", {}, result)
        self.assertEqual("verified", observed["status"])
        finished = orchestrator.finish(run_id, "completed", "Verificato")
        self.assertEqual("completed", finished["status"])
        self.assertEqual("completed", self.state.values["orchestration"]["value"]["status"])


if __name__ == "__main__":
    unittest.main()
