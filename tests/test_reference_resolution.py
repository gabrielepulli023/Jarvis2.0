import tempfile
import unittest
from pathlib import Path

from jarvis_core.events import EventBus
from jarvis_core.operational_context import OperationalContext
from jarvis_core.reference_resolution import (
    ReferenceResolver,
    compact_current_context,
    record_assistant_proposal,
    record_assistant_turn,
    record_operational_action,
    record_user_turn,
)
from jarvis_memory.store import MemoryStore


class FakeContext:
    def __init__(self):
        self.operational = OperationalContext()

    def operational_context(self):
        return self.operational.current()

    def snapshot(self):
        return {"active_window": None, "opened_apps": []}


class FakeRuntime:
    def __init__(self):
        self.memory = MemoryStore(Path(tempfile.mkdtemp()) / "memory.db")
        self.context = FakeContext()


class ReferenceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()

    def test_working_memory_focus_and_canonical_snapshot_shape(self):
        record_user_turn(self.runtime, "Confronta i7 12700 e Ultra 5 245K")
        self.assertEqual(self.runtime.memory.working.get("conversation.focus"), "Confronta i7 12700 e Ultra 5 245K")
        from jarvis_system.context import ContextEngine

        context = ContextEngine(EventBus(), type("State", (), {"snapshot": lambda _: {}})(), type("Processes", (), {"snapshot": lambda _: []})(), self.runtime.memory, type("Missions", (), {"recent": lambda *_: []})())
        self.assertEqual(context.snapshot()["conversation"]["focus"], "Confronta i7 12700 e Ultra 5 245K")
        context.close()

    def test_working_memory_ttl_expires(self):
        self.runtime.memory.working.set("conversation.focus", "temporaneo", ttl=0)
        self.assertIsNone(self.runtime.memory.working.get("conversation.focus"))

    def test_verified_application_and_pronoun_resolve(self):
        record_user_turn(self.runtime, "Apri Chrome")
        record_operational_action(self.runtime, "Apri Chrome", {"successo": True, "verification": {"status": "verified"}})
        result = ReferenceResolver(self.runtime).resolve("Chiudilo")
        self.assertTrue(result.resolved)
        self.assertEqual(result.value["name"], "Chrome")

    def test_ambiguous_candidates_require_clarification(self):
        record_user_turn(self.runtime, "Apri Chrome e Spotify")
        result = ReferenceResolver(self.runtime).resolve("Chiudilo")
        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.alternatives, ("Chrome", "Spotify"))

    def test_ordinals_and_other_are_deterministic(self):
        record_user_turn(self.runtime, "Apri Chrome e Spotify")
        second = ReferenceResolver(self.runtime).resolve("Apri il secondo")
        self.assertEqual(second.value["name"], "Spotify")
        self.runtime.memory.working.set("conversation.active_object", {"type": "application", "name": "Chrome"}, ttl=300)
        other = ReferenceResolver(self.runtime).resolve("Apri l'altro")
        self.assertEqual(other.value["name"], "Spotify")

    def test_operational_context_has_precedence_and_failures_expire(self):
        self.runtime.context.operational.record("file.create", {"successo": True, "verification": {"status": "verified"}, "dati": {"path": "C:/report.txt"}}, {})
        result = ReferenceResolver(self.runtime).resolve("Aprilo")
        self.assertEqual(result.source, "operational_context")
        self.runtime.context.operational.record("file.create", {"successo": False}, {})
        self.assertFalse(ReferenceResolver(self.runtime).resolve("Aprilo").resolved)

    def test_proposal_and_conversational_followup_stay_local_contextual(self):
        record_assistant_proposal(self.runtime, "Posso controllare anche i log.", focus="controllo log")
        result = ReferenceResolver(self.runtime).resolve("Fallo")
        self.assertTrue(result.resolved)
        self.assertEqual(result.reference_type, "conversational entity/topic")
        record_assistant_turn(self.runtime, "Ho completato il controllo.")
        self.assertIn("Ho completato", compact_current_context(self.runtime))

    def test_secret_is_redacted_from_compact_context(self):
        record_user_turn(self.runtime, "usa password: supersecret")
        self.assertNotIn("supersecret", compact_current_context(self.runtime))


if __name__ == "__main__":
    unittest.main()
