import unittest

from automation_intelligence import ActionMode, choose_policy, completion_allowed


class AutomationIntelligenceTests(unittest.TestCase):
    def test_ambiguous_target_without_context_requires_question(self):
        policy = choose_policy("Apri quello")
        self.assertEqual(policy.mode, ActionMode.ASK)
        self.assertTrue(policy.requires_clarification)

    def test_ui_action_requires_fresh_observation(self):
        policy = choose_policy("Clicca il pulsante play")
        self.assertEqual(policy.mode, ActionMode.OBSERVE_AND_ACT)
        self.assertTrue(policy.needs_observation)
        self.assertTrue(policy.needs_verification)

    def test_browser_prefers_dom_strategy(self):
        self.assertEqual(choose_policy("Clicca il risultato nella pagina Chrome").mode, ActionMode.BROWSER_DOM)

    def test_direct_action_still_requires_final_proof(self):
        policy = choose_policy("Apri Spotify")
        self.assertEqual(policy.mode, ActionMode.DIRECT)
        self.assertFalse(completion_allowed({"successo": True}, {"status": "unverified", "strength": 1}))
        self.assertTrue(completion_allowed({"successo": True}, {"status": "verified", "strength": .8}))


if __name__ == "__main__":
    unittest.main()
