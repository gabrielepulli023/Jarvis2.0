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

    def test_processa_domanda_reuses_one_operational_decision(self):
        import main

        worker = main.JarvisWorker()
        reference = SimpleNamespace(needs_clarification=False, resolved=False)
        decision = self.core.decide("Apri Chrome")
        cognition = SimpleNamespace(decide=Mock(return_value=decision))
        with patch.object(main.CORE_RUNTIME, "cognition", cognition), \
             patch.object(main, "record_user_turn"), \
             patch.object(main, "learn_explicit"), \
             patch.object(main, "resolve_reference", return_value=reference), \
             patch.object(main, "aggiungi_messaggio"), \
             patch.object(main, "update_context"), \
             patch.object(worker, "_comando_memoria_o_conferma", return_value=False), \
             patch.object(main, "get_setting", side_effect=lambda key, default=None: False if key == "async_engine_enabled" else default), \
             patch.object(main, "interpreta_comando", return_value=(True, "Chrome aperto", False)) as executor, \
             patch.object(main, "richiede_controllo_visivo", return_value=False), \
             patch.object(main, "match_expansion_skill", return_value=None), \
             patch.object(main, "_esegui_followup_operativo", return_value=None), \
             patch.object(worker, "_presenta_risultato", return_value=SimpleNamespace(spoken_response="Chrome aperto")), \
             patch.object(worker, "parla_controllato", return_value=None):
            worker.processa_domanda("Apri Chrome")
        cognition.decide.assert_called_once()
        self.assertIs(executor.call_args.kwargs["cognitive_decision"], decision)

    def test_processa_domanda_reuses_one_conversational_decision(self):
        import main

        worker = main.JarvisWorker()
        reference = SimpleNamespace(needs_clarification=False, resolved=False)
        decision = self.core.decide("Perché il cielo è blu?")
        cognition = SimpleNamespace(decide=Mock(return_value=decision))
        response = Mock(return_value=None)
        with patch.object(main.CORE_RUNTIME, "cognition", cognition), \
             patch.object(main, "record_user_turn"), \
             patch.object(main, "learn_explicit"), \
             patch.object(main, "resolve_reference", return_value=reference), \
             patch.object(worker, "_comando_memoria_o_conferma", return_value=False), \
             patch.object(worker, "risposta_ai", response), \
             patch.object(main, "get_setting", return_value=False):
            worker.processa_domanda("Perché il cielo è blu?")
        cognition.decide.assert_called_once()
        self.assertIs(response.call_args.args[1], decision)

    def test_brain_supplied_conversational_decision_blocks_fast_and_expansion(self):
        import brain

        decision = self.core.decide("Non salvare nella memoria vettoriale")
        with patch.object(brain, "_interpreta_comando_locale") as fast, \
             patch.object(brain, "_interpreta_expansion_deterministica") as expansion, \
             patch.object(brain, "esegui_tool") as execute:
            result = brain.interpreta_comando("salva memoria vettoriale", cognitive_decision=decision)
        self.assertEqual(result, (False, None, False))
        fast.assert_not_called()
        expansion.assert_not_called()
        execute.assert_not_called()

    def test_supplied_non_operational_decision_cannot_be_upgraded_by_expansion(self):
        import main

        decision = self.core.decide("Non salvare nella memoria vettoriale")
        with patch.object(main, "match_expansion_skill", return_value=object()):
            self.assertFalse(main.deve_usare_router_operativo("salva memoria vettoriale", cognitive_decision=decision))

    def test_mission_policy_and_target_typing_are_shared(self):
        from cognitive_core import mission_required

        self.assertFalse(mission_required("Apri Chrome"))
        self.assertTrue(mission_required("Crea un progetto completo, testalo e correggi ogni errore"))
        self.assertFalse(mission_required("Spiegami come creare un progetto completo, testarlo e correggerlo"))
        artifact = self.core.decide("Apri report.txt")
        self.assertEqual(artifact.target_type, "artifact")
        self.assertNotIn("world", artifact.confidence_components)


if __name__ == "__main__":
    unittest.main()
