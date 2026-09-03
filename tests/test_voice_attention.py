import unittest

from decision_layer import resolve_control_intent
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_voice.attention import AttentionController, AttentionState


class VoiceAttentionTests(unittest.TestCase):
    def setUp(self):
        self.state = StateManager(EventBus())
        self.attention = AttentionController(self.state)

    def test_ambient_question_is_not_addressed(self):
        result = self.attention.evaluate("Mamma cosa mangiamo a cena?")
        self.assertFalse(result.addressed)

    def test_explicit_wake_is_maximum_confidence(self):
        result = self.attention.evaluate("Jarvis")
        self.assertTrue(result.addressed)
        self.assertEqual(result.confidence, 1.0)
        self.assertTrue(result.explicit_wake)

    def test_open_conversation_resolves_reference(self):
        result = self.attention.evaluate("Aprilo", conversation_open=True, has_context=True)
        self.assertTrue(result.addressed)

    def test_owner_operational_request_can_pass_without_wake(self):
        result = self.attention.evaluate("Apri Chrome", owner_speaker=True, activity_relevant=True)
        self.assertTrue(result.addressed)

    def test_ambiguous_operation_stays_closed(self):
        result = self.attention.evaluate("Apri Chrome")
        self.assertFalse(result.addressed)

    def test_control_mute_is_central_and_semantic(self):
        self.assertEqual(resolve_control_intent("Jarvis, zitto", addressed=True).name, "mute")
        self.assertEqual(resolve_control_intent("Muto", conversation_open=True).name, "mute")
        self.assertEqual(resolve_control_intent("Non parlo con te", conversation_open=True).name, "mute")

    def test_basta_ambient_is_not_mute(self):
        self.assertIsNone(resolve_control_intent("Basta", addressed=False, conversation_open=False))

    def test_muted_accepts_only_explicit_wake(self):
        self.attention.mute()
        self.assertEqual(self.attention.state, AttentionState.MUTED)
        self.assertFalse(self.attention.accepts("Apri Chrome", owner_speaker=True).addressed)
        self.assertTrue(self.attention.accepts("Jarvis").explicit_wake)
        self.attention.wake_from_mute()
        self.assertEqual(self.attention.state, AttentionState.ENGAGED)


if __name__ == "__main__":
    unittest.main()
