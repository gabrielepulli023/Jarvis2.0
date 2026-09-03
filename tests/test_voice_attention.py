import unittest
from unittest.mock import patch

from decision_layer import resolve_control_intent
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_voice.attention import AttentionController, AttentionState
from settings_store import get_setting


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

    def test_standard_configuration_activates_selective_path(self):
        self.assertTrue(get_setting("continuous_listening"))
        self.assertFalse(get_setting("wake_word_only_standby"))

    def test_unverified_permission_session_is_not_speaker_evidence(self):
        result = self.attention.evaluate("Apri Chrome", owner_speaker=None)
        self.assertFalse(result.addressed)

    def test_non_owner_and_unknown_are_distinct(self):
        non_owner = self.attention.evaluate("Apri Chrome", owner_speaker=False)
        unknown = self.attention.evaluate("Apri Chrome", owner_speaker=None)
        self.assertIn("unknown_or_non_owner_speaker", non_owner.reasons)
        self.assertNotIn("unknown_or_non_owner_speaker", unknown.reasons)
        self.assertFalse(non_owner.addressed)
        self.assertFalse(unknown.addressed)

    def test_voiceprint_owner_and_other_profile(self):
        from main import JarvisWorker

        worker = JarvisWorker.__new__(JarvisWorker)
        pcm = b"\x01\x00" * (16000 // 2)
        fake_identity = type("Identity", (), {
            "status": lambda self: {"voice_profiles": ["gabriele", "mamma"]},
            "recognize_voice_samples": lambda self, *args, **kwargs: {"matched": True, "name": "gabriele"},
        })()
        with patch("main.IDENTITY", fake_identity), patch("main.get_setting", side_effect=lambda key, default=None: {
            "biometric_identity_enabled": True,
            "voice_match_threshold": .88,
            "ceo_profile_name": "gabriele",
        }.get(key, default)):
            self.assertTrue(worker._owner_speaker_from_audio(pcm))
            fake_identity.recognize_voice_samples = lambda *args, **kwargs: {"matched": True, "name": "mamma"}
            self.assertFalse(worker._owner_speaker_from_audio(pcm))

    def test_voiceprint_unavailable_returns_unknown(self):
        from main import JarvisWorker

        worker = JarvisWorker.__new__(JarvisWorker)
        class UnavailableIdentity:
            def status(self):
                raise RuntimeError("unavailable")

        with patch("main.IDENTITY", UnavailableIdentity()):
            self.assertIsNone(worker._owner_speaker_from_audio(b"\x01\x00" * 8000))


if __name__ == "__main__":
    unittest.main()
