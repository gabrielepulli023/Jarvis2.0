import unittest

from decision_layer import IntentKind, Strategy, decide


class DecisionLayerTests(unittest.TestCase):
    def test_question_is_answered_without_tools(self):
        decision = decide("Perché il cielo è blu?")
        self.assertEqual(decision.kind, IntentKind.INFORMATION)
        self.assertEqual(decision.strategy, Strategy.ANSWER)
        self.assertFalse(decision.needs_tools)

    def test_explicit_ui_request_observes_before_acting(self):
        decision = decide("Clicca il pulsante play nella pagina")
        self.assertTrue(decision.needs_tools)
        self.assertTrue(decision.needs_observation)
        self.assertEqual(decision.strategy, Strategy.OBSERVE_THEN_ACT)

    def test_direct_program_request_does_not_require_mouse(self):
        decision = decide("Apri la calcolatrice")
        self.assertTrue(decision.needs_tools)
        self.assertFalse(decision.needs_observation)
        self.assertEqual(decision.strategy, Strategy.USE_TOOLS)

    def test_compound_request_plans_and_verifies(self):
        decision = decide("Apri Chrome, cerca il sito e poi verifica il risultato")
        self.assertEqual(decision.kind, IntentKind.COMPOSITE)
        self.assertEqual(decision.strategy, Strategy.PLAN_AND_VERIFY)

    def test_capability_question_is_not_an_operation(self):
        decision = decide("Puoi usare mouse e tastiera?")
        self.assertEqual(decision.kind, IntentKind.CAPABILITY)
        self.assertFalse(decision.needs_tools)

    def test_context_reference_activates_observation_only_when_context_exists(self):
        self.assertFalse(decide("Guarda quello", has_context=False).needs_tools)
        self.assertTrue(decide("Guarda quello", has_context=True).needs_tools)


if __name__ == "__main__":
    unittest.main()
