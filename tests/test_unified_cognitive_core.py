import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from types import SimpleNamespace

from jarvis_core.cognitive_core import IntentKind, UnifiedCognitiveCore
from jarvis_skills import Capability, SkillManifest, SkillRegistry


class UnifiedCognitiveCoreTests(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry(Path(tempfile.mkdtemp()) / "metrics.db")
        self.registry.register(
            SkillManifest("lights.dim", "1.0.0", "Dim room lights", ("abbassa le luci", "riduci luminosita stanza"), frozenset({Capability.SYSTEM_SETTINGS}), "test:lights"),
            lambda: {"success": True, "message": "ok"},
        )
        self.core = UnifiedCognitiveCore(registry=self.registry)

    def test_semantic_requests_and_questions(self):
        for text in ("Apri Chrome", "Mi apri Chrome per favore?", "Potresti aprirmi Chrome?", "Fammi partire Spotify", "Riesci ad alzare un po' il volume?"):
            self.assertEqual(self.core.decide(text).intent_kind, IntentKind.OPERATION)
        for text in ("Come si chiude Chrome?", "Puoi spiegarmi come chiudere Chrome?", "Volevo sapere come aprire Chrome", "Cosa succede se chiudo Chrome?"):
            self.assertEqual(self.core.decide(text).intent_kind, IntentKind.INFORMATION)

    def test_negation_and_mission_detection(self):
        denied = self.core.decide("Non chiudere Chrome")
        self.assertTrue(denied.negated)
        self.assertFalse(denied.needs_tools)
        self.assertFalse(self.core.decide("Spiegami dettagliatamente come funziona il protocollo TCP " * 8).mission_required)
        self.assertTrue(self.core.decide("Apri Chrome, cerca YouTube e poi riproduci il primo video").mission_required)

    def test_future_skill_is_registry_backed(self):
        decision = self.core.decide("Mi abbassi un po' le luci?")
        self.assertIn("lights.dim", decision.candidate_skills)

    def test_decision_is_bounded_and_reference_is_preserved(self):
        reference = SimpleNamespace(resolved=True, value={"name": "Chrome"}, reference_type="application")
        decision = self.core.decide("Chiudilo", resolved_operational_text="chiudi Chrome", reference=reference, attention=.9)
        self.assertEqual(decision.target, "Chrome")
        self.assertEqual(decision.original_user_text, "Chiudilo")
        self.assertEqual(decision.resolved_operational_text, "chiudi Chrome")
        self.assertEqual(decision.confidence_components["attention"], .9)
        self.assertLessEqual(len(str(decision.to_dict())), 6000)

    def test_main_helper_builds_one_shared_decision(self):
        import main

        expected = self.core.decide("Apri Chrome")
        cognition = Mock()
        cognition.decide.return_value = expected
        with patch.object(main.CORE_RUNTIME, "cognition", cognition):
            actual = main._prepare_cognitive_turn("Apri Chrome", "Apri Chrome")
        self.assertIs(actual, expected)
        cognition.decide.assert_called_once()

    def test_provider_uses_supplied_decision(self):
        from provider_router import classify_task

        decision = self.core.decide("Apri Chrome")
        with patch("provider_router.decide_intent") as classifier:
            self.assertEqual(classify_task("testo non operativo", decision), "tool_execution")
        classifier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
