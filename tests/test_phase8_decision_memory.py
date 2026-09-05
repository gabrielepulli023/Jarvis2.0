import json
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_memory import ContextBuilder, DecisionMemory, DecisionOutcome, MemoryKind, MemoryStore
from jarvis_missions import MissionStore
from jarvis_missions.graph import Task, TaskGraph
from jarvis_core.orchestrator import AutonomousOrchestrator
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_companion import CompanionEngine, InterventionCandidate, Decision as CompanionDecision
from jarvis_personality import PersonalityEngine


class Registry:
    def list(self): return []
    def manifest(self, name): return None


def decision(text="ripristino audio Bluetooth", strategy="use_tools"):
    return SimpleNamespace(original_user_text=text, intent_kind="operation", strategy=strategy,
                           semantic_action="audio.fix", target_type="device", risk_hint="safe",
                           confidence=.82, candidate_skills=("audio.fix",), reasons=("canonical_intent",))


class Phase8DecisionMemoryTests(unittest.TestCase):
    def make(self, get=None):
        directory = tempfile.TemporaryDirectory()
        store = MemoryStore(Path(directory.name) / "memory.db")
        return directory, store, DecisionMemory(store, settings_get=get or (lambda key, default=None: default))

    def test_kind_and_pending_are_volatile(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        self.assertEqual(MemoryKind.DECISION.value, "decision")
        pending = memory.observe_decision(decision())
        self.assertEqual(pending["candidate_skills"], ("audio.fix",))
        self.assertEqual(len(store.search("Bluetooth", kind=MemoryKind.DECISION)), 0)
        self.assertEqual(len(store.working.namespace("decision.pending.")), 1)

    def test_observation_does_not_mutate_decision_or_persist_raw_text(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        item = decision()
        before = vars(item).copy()
        memory.observe_decision(item)
        self.assertEqual(vars(item), before)
        pending = next(iter(store.working.namespace("decision.pending.").values()))
        self.assertNotIn("original_user_text", pending)
        self.assertNotIn("resolved_operational_text", pending)

    def test_verified_success_and_failure_timeout(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        success = memory.record_outcome({"objective": "ripristino audio Bluetooth", "outcome": "verified_success",
                                         "verified": True, "selected_skills": ["audio.fix"], "observed_event_codes": ["mission.completed"]})
        failed = memory.record_outcome({"objective": "ripristino audio Bluetooth", "outcome": "failed",
                                        "reason_codes": ["timeout"], "observed_event_codes": ["task.timeout"]})
        self.assertEqual(success.outcome, DecisionOutcome.VERIFIED_SUCCESS)
        self.assertTrue(success.verified)
        self.assertEqual(failed.reason_codes, ("timeout",))
        self.assertEqual(len(store.search("audio Bluetooth", kind=MemoryKind.DECISION)), 2)

    def test_pending_merges_canonical_decision_metadata_and_is_consumed(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        cognitive = decision("open Chrome", strategy="PLAN_AND_VERIFY")
        cognitive.semantic_action = "open"
        cognitive.risk_hint = "sensitive"
        cognitive.candidate_skills = ("windows.open",)
        memory.observe_decision(cognitive, objective="open Chrome")
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=memory)
        run_id = orchestrator.begin("open Chrome")
        orchestrator.observe(run_id, "windows.open", {}, {"success": True, "verification": {"status": "verified"}, "skill": "windows.open"})
        orchestrator.finish(run_id, "completed", "done")
        record = memory.recall("open Chrome")[0]
        self.assertEqual(record.strategy, "PLAN_AND_VERIFY")
        self.assertEqual(record.semantic_action, "open")
        self.assertEqual(record.risk_hint, "sensitive")
        self.assertEqual(record.candidate_skills, ("windows.open",))
        self.assertTrue(record.verified)
        self.assertEqual(store.working.namespace("decision.pending."), {})

    def test_decision_reasons_confidence_and_event_sequence_are_preserved(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        cognitive = decision("recover audio", strategy="PLAN_AND_VERIFY")
        cognitive.reasons = ("canonical_intent", "context_reference")
        cognitive.confidence = .82
        memory.observe_decision(cognitive, objective="recover audio")
        record = memory.record_mission_outcome("recover audio", {
            "outcome": "verified_success", "verified": True,
            "selected_skills": ("A", "A", "B"),
            "observed_event_codes": ("task.failed", "task.recovered", "mission.completed"),
            "fallback_used": ("B",), "reason_codes": ("fallback_recovered",),
        })
        self.assertEqual(record.decision_reasons, ("canonical_intent", "context_reference"))
        self.assertEqual(record.decision_confidence, .82)
        self.assertEqual(record.selected_skills, ("A", "B"))
        self.assertEqual(record.observed_event_codes, ("task.failed", "task.recovered", "mission.completed"))
        self.assertEqual(record.reason_codes, ("fallback_recovered",))

    def test_newest_pending_wins_and_concurrent_resolve_consumes_once(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        memory.observe_decision(decision("same objective", strategy="old"), objective="same objective")
        memory.observe_decision(decision("same objective", strategy="new"), objective="same objective")
        newest = memory.resolve_pending("same objective")
        self.assertEqual(newest["strategy"], "new")
        memory.resolve_pending("same objective")
        memory.observe_decision(decision("same objective", strategy="single"), objective="same objective")
        consumed = []
        threads = [threading.Thread(target=lambda: consumed.append(memory.resolve_pending("same objective"))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(value is not None for value in consumed), 1)
        self.assertEqual(next(value for value in consumed if value is not None)["strategy"], "single")

    def test_outcome_states_and_no_raw_payload(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        for outcome in ("success_unverified", "blocked", "cancelled", "partial"):
            memory.record({"objective": "safe task", "outcome": outcome, "reason_codes": ["cancelled"] if outcome == "cancelled" else []})
        rows = store.search("safe task", kind=MemoryKind.DECISION)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all("password" not in row["content"].lower() for row in rows))

    def test_dedup_and_occurrences(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        payload = {"objective": "repeat audio", "outcome": "verified_success", "verified": True}
        for _ in range(100): memory.record(payload)
        rows = store.search("repeat audio", kind=MemoryKind.DECISION)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["content"])["occurrences"], 1)
        self.assertEqual(rows[0]["metadata"]["occurrences"], 100)
        self.assertEqual(memory.recall("repeat audio")[0].occurrences, 100)

    def test_storage_block_does_not_hold_decision_lock(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        entered, release = threading.Event(), threading.Event()
        original = store.remember_or_increment
        def blocking(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        with patch.object(store, "remember_or_increment", side_effect=blocking):
            worker = threading.Thread(target=lambda: memory.record({"objective": "blocked storage", "outcome": "failed"}))
            worker.start()
            self.assertTrue(entered.wait(1))
            memory.observe_decision(decision("in-memory while storage waits"))
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_concurrent_recording_uses_one_storage_item_and_100_occurrences(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        threads = [threading.Thread(target=lambda: memory.record({"objective": "same concurrent decision", "outcome": "verified_success", "verified": True})) for _ in range(100)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        rows = store.list_metadata(kind=MemoryKind.DECISION)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metadata"]["occurrences"], 100)

    def test_actual_orchestrator_path_deduplicates_runs_and_splits_outcomes(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=memory)
        for index in range(100):
            run_id = orchestrator.begin("same mission")
            orchestrator.observe(run_id, "audio.fix", {"run_id": index}, {"success": True, "verification": {"status": "verified"}, "skill": "audio.fix", "observed_at": index})
            orchestrator.finish(run_id, "completed", "done")
        failed = orchestrator.begin("same mission")
        orchestrator.observe(failed, "audio.fix", {}, {"success": False, "skill": "audio.fix", "result_payload": "not stored"})
        orchestrator.finish(failed, "failed", "failed")
        rows = store.list_metadata(kind=MemoryKind.DECISION, limit=10)
        self.assertEqual(len(rows), 2)
        occurrences = sorted(row["metadata"]["occurrences"] for row in rows)
        self.assertEqual(occurrences, [1, 100])

    def test_conflicts_and_lessons_are_advisory(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        for _ in range(8): memory.record({"objective": "Chrome", "strategy": "open", "outcome": "verified_success", "verified": True})
        for _ in range(2): memory.record({"objective": "Chrome", "strategy": "open", "outcome": "failed", "reason_codes": ["action_error"]})
        lessons = memory.lessons("Chrome")
        self.assertEqual((lessons["verified_successes"], lessons["failures"]), (8, 2))
        self.assertLess(lessons["confidence"], 1)
        self.assertTrue(lessons["advisory_only"])

    def test_lessons_strength_tracks_coherent_dominant_evidence(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        memory.record({"objective": "coherent", "outcome": "verified_success", "verified": True})
        self.assertEqual(memory.lessons("coherent")["strength"], "anecdotal")
        memory.record({"objective": "coherent", "outcome": "verified_success", "verified": True})
        self.assertEqual(memory.lessons("coherent")["strength"], "weak")
        memory.record({"objective": "coherent", "outcome": "verified_success", "verified": True})
        self.assertEqual(memory.lessons("coherent")["strength"], "supported")
        memory.record({"objective": "coherent", "outcome": "failed"})
        lessons = memory.lessons("coherent")
        self.assertEqual(lessons["sample_size"], 4)
        self.assertLess(lessons["confidence"], 1.0)

    def test_recovery_is_observed_association_not_causal_certainty(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        record = memory.record({"objective": "fix audio", "outcome": "verified_success", "verified": True,
                                "selected_skills": ["audio.primary", "audio.fallback"],
                                "fallback_used": ["audio.fallback"], "reason_codes": ["fallback_recovered"],
                                "causality": "observed_association"})
        self.assertEqual(record.causality.value, "observed_association")
        self.assertEqual(record.fallback_used, ("audio.fallback",))
        self.assertNotEqual(record.causality.value, "verified_cause")

    def test_recall_ranking_and_context_builder(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        memory.record({"objective": "ripristino audio Bluetooth", "outcome": "verified_success", "verified": True})
        records = memory.recall("problema audio Bluetooth")
        self.assertEqual(records[0].outcome, DecisionOutcome.VERIFIED_SUCCESS)
        context = ContextBuilder(store, max_chars=1000).build("problema audio Bluetooth")
        self.assertTrue(any(item.kind == MemoryKind.DECISION.value for item in context))

    def test_privacy_and_sensitive_rejection(self):
        directory, store, memory = self.make(lambda key, default=None: True if key == "privacy_mode" else default)
        self.addCleanup(directory.cleanup)
        self.assertIsNone(memory.observe_decision(decision()))
        self.assertIsNone(memory.record({"objective": "private", "outcome": "failed"}))
        self.assertEqual(memory.recall("private"), ())
        directory2, store2, memory2 = self.make()
        self.addCleanup(directory2.cleanup)
        with self.assertRaises(ValueError): memory2.record({"objective": "save password: secret", "outcome": "failed"})

    def test_pending_limit_preserves_foreign_working_memory(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        store.working.set("other.component.value", {"keep": True})
        for index in range(1000): memory.observe_decision(decision(f"pending {index}"))
        self.assertLessEqual(len(store.working.namespace("decision.pending.")), 32)
        self.assertEqual(store.working.get("other.component.value"), {"keep": True})

    def test_bounded_pending_and_no_auto_execution(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        for index in range(1000): memory.observe_decision(decision(f"task {index}"))
        self.assertLessEqual(store.working.stats()["entries"], 512)
        self.assertFalse(hasattr(memory, "execute"))
        self.assertFalse(hasattr(memory, "run_plan"))

    def test_orchestrator_verified_success_and_recovery(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=memory)
        run_id = orchestrator.begin("fix audio")
        orchestrator.observe(run_id, "audio.fix", {}, {"success": True, "verification": {"status": "verified"}, "skill": "audio.fix"})
        result = orchestrator.finish(run_id, "completed", "done")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(memory.recall("fix audio")[0].outcome, DecisionOutcome.VERIFIED_SUCCESS)

    def test_real_orchestrator_missionstore_recovery_proof(self):
        directory, store, _ = self.make()
        self.addCleanup(directory.cleanup)
        mission_store = MissionStore(Path(directory.name) / "missions.db")
        mission_id = mission_store.create("real recovered mission", TaskGraph([Task("a", "audio")] ))
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="running", event="task.failed")
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="running", event="task.recovered")
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="completed", event="mission.completed")
        memory = DecisionMemory(store, mission_store=mission_store)
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=memory)
        self.assertEqual(orchestrator.begin("real recovered mission", run_id=mission_id), mission_id)
        orchestrator.observe(mission_id, "audio.primary", {}, {"success": False, "skill": "audio.primary"})
        orchestrator.observe(mission_id, "audio.fallback", {}, {"success": True, "verification": {"status": "verified"}, "skill": "audio.fallback"})
        orchestrator.finish(mission_id, "completed", "recovered")
        record = memory.recall("real recovered mission")[0]
        self.assertEqual(record.outcome, DecisionOutcome.VERIFIED_SUCCESS)
        self.assertEqual(record.causality.value, "observed_association")
        self.assertEqual(record.observed_event_codes, ("task.failed", "task.recovered", "mission.completed"))
        self.assertIn("fallback_recovered", record.reason_codes)

    def test_orchestrator_failed_timeout_and_cancelled(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=memory)
        first = orchestrator.begin("timeout task")
        orchestrator.finish(first, "timeout", "timeout")
        second = orchestrator.begin("cancel task")
        orchestrator.finish(second, "cancelled", "cancelled")
        self.assertEqual(memory.recall("timeout task")[0].reason_codes, ("timeout",))
        self.assertEqual(memory.recall("cancel task")[0].outcome, DecisionOutcome.CANCELLED)

    def test_orchestrator_persistence_failure_is_isolated(self):
        class Failing:
            def record_mission_outcome(self, objective, evidence): raise OSError("memory unavailable")
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=Failing())
        run_id = orchestrator.begin("resilient")
        result = orchestrator.finish(run_id, "failed", "failure")
        self.assertEqual(result["status"], "failed")

    def test_orchestrator_snapshot_available_while_memory_callback_blocks(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking:
            @staticmethod
            def fingerprint(objective, decision): return "proof"
            def record_mission_outcome(self, objective, data):
                entered.set(); release.wait(2)
        orchestrator = AutonomousOrchestrator(Registry(), decision_memory=Blocking())
        run_id = orchestrator.begin("blocked callback")
        worker = threading.Thread(target=lambda: orchestrator.finish(run_id, "failed", "x"))
        worker.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(orchestrator.snapshot(run_id)["status"], "failed")
        release.set(); worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_mission_store_events_are_the_evidence_source(self):
        directory, store, _ = self.make()
        self.addCleanup(directory.cleanup)
        mission_store = MissionStore(Path(directory.name) / "missions.db")
        mission_id = mission_store.create("mission evidence", TaskGraph([Task("a", "audio")]))
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="failed", event="task.timeout")
        memory = DecisionMemory(store, mission_store=mission_store)
        record = memory.record_mission_outcome("mission evidence", {"mission_id": mission_id, "outcome": "verified_success", "verified": True})
        self.assertEqual(record.outcome, DecisionOutcome.FAILED)
        self.assertIn("task.timeout", record.observed_event_codes)
        self.assertIn("timeout", record.reason_codes)

    def test_final_mission_status_and_recent_events_win(self):
        directory, store, _ = self.make()
        self.addCleanup(directory.cleanup)
        mission_store = MissionStore(Path(directory.name) / "missions.db")
        mission_id = mission_store.create("recovered mission", TaskGraph([Task("a", "audio")]))
        for index in range(10):
            mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="running", event=f"task.progress_{index}")
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="completed", event="task.failed")
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="completed", event="task.recovered")
        mission_store.save(mission_id, TaskGraph([Task("a", "audio")]), status="completed", event="mission.completed")
        memory = DecisionMemory(store, mission_store=mission_store)
        record = memory.record_mission_outcome("recovered mission", {"mission_id": mission_id, "outcome": "failed"})
        self.assertEqual(record.outcome, DecisionOutcome.VERIFIED_SUCCESS)
        self.assertEqual(record.observed_event_codes[-2:], ("task.recovered", "mission.completed"))
        self.assertIn("fallback_recovered", record.reason_codes)

    def test_status_does_not_increment_use_count(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        memory.record({"objective": "status query", "outcome": "verified_success", "verified": True})
        content = store.list_metadata(kind=MemoryKind.DECISION)[0]["content"]
        before = store.find_exact(content, kind=MemoryKind.DECISION)["use_count"]
        for _ in range(100): memory.status()
        after = store.find_exact(content, kind=MemoryKind.DECISION)["use_count"]
        self.assertEqual(before, after)

    def test_main_wrapper_observes_same_object_fail_safe(self):
        import main
        expected = decision("wrapper")
        captured = []
        class Cognition:
            def decide(self, *args, **kwargs): return expected
        class DecisionObserver:
            def observe_decision(self, value, **kwargs): captured.append(value)
        runtime = SimpleNamespace(cognition=Cognition(), decision_memory=DecisionObserver())
        with patch.object(main, "CORE_RUNTIME", runtime):
            returned = main._prepare_cognitive_turn("wrapper", "wrapper")
        self.assertIs(returned, expected)
        self.assertIs(captured[0], expected)

        class FailingObserver:
            def observe_decision(self, *args, **kwargs): raise RuntimeError("memory down")
        runtime.decision_memory = FailingObserver()
        with patch.object(main, "CORE_RUNTIME", runtime):
            self.assertIs(main._prepare_cognitive_turn("wrapper", "wrapper"), expected)

    def test_phase7_and_phase6_are_not_dependencies(self):
        directory, store, memory = self.make()
        self.addCleanup(directory.cleanup)
        record = memory.record({"objective": "same", "outcome": "verified_success", "verified": True})
        PersonalityEngine(settings_get=lambda key, default=None: {}, settings_set=lambda key, value: None).select_style("ciao")
        self.assertEqual(record.fingerprint, memory.recall("same")[0].fingerprint)
        candidate = InterventionCandidate("r", "s", "coding", "m", .95, .95, relevance=1, novelty=1,
                                          urgency=.6, interruption_cost=.1, critical=True)
        bus = EventBus(); state = StateManager(bus)
        with tempfile.TemporaryDirectory() as path:
            companion = CompanionEngine(bus, state, SimpleNamespace(state="idle", submit=lambda *args, **kwargs: "id"), config={"mode": "companion"}, persistence_path=Path(path) / "c.json")
            self.assertEqual(companion.evaluate(candidate), CompanionDecision.SPEAK_HIGH_PRIORITY)


if __name__ == "__main__": unittest.main()
