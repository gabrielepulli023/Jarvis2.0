import json
import tempfile
import unittest
from pathlib import Path

from jarvis_companion import CompanionEngine, CompanionMode, Decision, InterventionCandidate
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_voice import VoiceState
from main import comando_modalita_companion, contestualizza_risposta_companion


class FakeVoice:
    def __init__(self): self.state, self.submitted = VoiceState.IDLE, []
    def submit(self, text, priority, interruptible):
        self.submitted.append((text, priority, interruptible)); return f"speech-{len(self.submitted)}"


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


def candidate(**changes):
    values = dict(reason="useful", source="test", category="coding", message="Messaggio utile",
                  importance=.95, confidence=.95, relevance=1, novelty=1, urgency=.6,
                  interruption_cost=.1, fingerprint="same")
    values.update(changes); return InterventionCandidate(**values)


class CompanionTests(unittest.TestCase):
    def make_engine(self, config=None):
        bus, voice, clock = EventBus(), FakeVoice(), Clock()
        engine = CompanionEngine(bus, StateManager(bus), voice, config=config or {}, clock=clock)
        engine.start(); self.addCleanup(engine.stop)
        return engine, bus, voice, clock

    def test_passive_never_speaks_and_silence_is_counted(self):
        engine, _, voice, _ = self.make_engine({"mode": "passive"})
        self.assertEqual(engine.evaluate(candidate()), Decision.SILENCE)
        self.assertEqual(voice.submitted, [])
        self.assertEqual(engine.snapshot()["metrics"]["silence_decisions"], 1)

    def test_focus_and_busy_voice_suppress_noncritical_speech(self):
        engine, _, voice, _ = self.make_engine({"mode": "focus"})
        self.assertEqual(engine.evaluate(candidate()), Decision.HUD_ONLY)
        self.assertEqual(voice.submitted, [])
        engine.set_mode(CompanionMode.COMPANION); voice.state = VoiceState.LISTENING
        self.assertEqual(engine.evaluate(candidate(fingerprint="busy")), Decision.HUD_ONLY)

    def test_low_confidence_is_silent(self):
        engine, _, voice, _ = self.make_engine({"mode": "companion"})
        self.assertEqual(engine.evaluate(candidate(confidence=.2)), Decision.SILENCE)
        self.assertFalse(voice.submitted)

    def test_repeated_coding_failure_is_end_to_end_and_deduplicated(self):
        engine, bus, voice, _ = self.make_engine({"mode": "companion", "coding_enabled": True})
        for _ in range(3): bus.publish("test.failed", {"signature": "AssertionError: audio"}, source="test-runner", confidence=.98)
        self.assertEqual(len(voice.submitted), 1)
        self.assertTrue(voice.submitted[0][2])
        pending = engine.consume_pending_context()
        self.assertEqual(pending["reason"], "repeated_test_failure")
        bus.publish("test.failed", {"signature": "AssertionError: audio"}, source="test-runner", confidence=.98)
        self.assertEqual(len(voice.submitted), 1)
        self.assertGreaterEqual(engine.snapshot()["metrics"]["duplicate_suppressions"], 1)

    def test_new_memory_incident_is_not_duplicate_within_cooldown(self):
        engine, bus, voice, _ = self.make_engine({
            "mode": "companion", "budget_capacity": 10, "speak_threshold": 0,
            "hud_threshold": 0, "duplicate_cooldown_seconds": 900,
        })
        decisions = []
        bus.subscribe("companion.decision", decisions.append)
        first = bus.publish("system.memory_pressure", {"value": 92, "incident_id": "memory-1"},
                            source="system_signals", confidence=1.0)
        second = bus.publish("system.memory_pressure", {"value": 92, "incident_id": "memory-2"},
                             source="system_signals", confidence=1.0)
        repeated = bus.publish("system.memory_pressure", {"value": 92, "incident_id": "memory-2"},
                               source="system_signals", confidence=1.0)
        self.assertNotEqual(engine._candidate_from(first).fingerprint, engine._candidate_from(second).fingerprint)
        self.assertEqual(engine._candidate_from(second).fingerprint, engine._candidate_from(repeated).fingerprint)
        self.assertEqual([record.payload["reason"] for record in decisions], ["approved", "approved", "duplicate"])
        self.assertEqual([record.payload["cooldown"] for record in decisions], [False, False, True])
        self.assertEqual(len(voice.submitted), 2)

    def test_spontaneous_turn_continues_in_normal_conversation(self):
        prompt = contestualizza_risposta_companion("Sì, controllalo.", {"message": "L'errore continua. Vuoi che controlli?"})
        self.assertIn("L'errore continua", prompt)
        self.assertIn("Sì, controllalo.", prompt)
        self.assertEqual(contestualizza_risposta_companion("ciao", None), "ciao")

    def test_focus_voice_commands_are_deterministic(self):
        self.assertEqual(comando_modalita_companion("Jarvis non interrompermi"), "focus")
        self.assertEqual(comando_modalita_companion("Jarvis modalità focus"), "focus")
        self.assertEqual(comando_modalita_companion("Jarvis esci dalla modalità focus"), "companion")
        self.assertEqual(comando_modalita_companion("Jarvis puoi tornare a parlare"), "companion")
        self.assertIsNone(comando_modalita_companion("apri il browser"))

    def test_event_storm_is_bounded_and_speaks_once(self):
        engine, bus, voice, _ = self.make_engine({"mode": "companion", "coding_enabled": True})
        for _ in range(1000):
            bus.publish("test.failed", {"signature": "storm"}, source="runner", confidence=.99)
        self.assertEqual(len(voice.submitted), 1)
        self.assertLessEqual(len(engine._coding_failures), 64)
        self.assertEqual(engine.snapshot()["metrics"]["spontaneous_interventions"], 1)

    def test_coding_off_ignores_test_events(self):
        _, bus, voice, _ = self.make_engine({"mode": "companion", "coding_enabled": False})
        for _ in range(5): bus.publish("test.failed", {"signature": "same"})
        self.assertFalse(voice.submitted)

    def test_budget_recovers_and_cooldown_expires(self):
        engine, _, voice, clock = self.make_engine({"mode": "companion", "budget_capacity": 1,
            "budget_recovery_per_hour": 1, "duplicate_cooldown_seconds": 100})
        self.assertEqual(engine.evaluate(candidate()), Decision.SPEAK)
        self.assertEqual(engine.evaluate(candidate(fingerprint="other")), Decision.HUD_ONLY)
        clock.advance(3600)
        self.assertEqual(engine.evaluate(candidate(fingerprint="third")), Decision.SPEAK)
        self.assertEqual(len(voice.submitted), 2)

    def test_bad_subscriber_or_malformed_event_cannot_break_bus(self):
        engine, bus, _, _ = self.make_engine({"mode": "companion", "coding_enabled": True})
        received = []; bus.subscribe("test.failed", received.append)
        bus.publish("test.failed", {"traceback": object()}, confidence=.9)
        self.assertEqual(len(received), 1)
        self.assertEqual(engine.snapshot()["metrics"].get("errors", 0), 0)

    def test_invalid_config_falls_back_and_persistence_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            bus, voice = EventBus(), FakeVoice()
            engine = CompanionEngine(bus, StateManager(bus), voice,
                config={"mode": "invalid", "minimum_confidence": "bad"}, persistence_path=path)
            self.assertEqual(engine.snapshot()["mode"], "normal")
            engine.set_mode("focus"); engine.stop()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["config"]["mode"], "focus")
            path.write_text("not-json", encoding="utf-8")
            recovered = CompanionEngine(bus, StateManager(bus), voice, persistence_path=path)
            self.assertEqual(recovered.snapshot()["mode"], "normal")


if __name__ == "__main__": unittest.main()
