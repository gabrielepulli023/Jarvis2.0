import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_missions.engine import MissionEngine
from jarvis_missions.planner import MissionPlanner, MissionToolCatalogAdapter
from jarvis_missions.store import MissionStore


class _Registry:
    def __init__(self):
        self.executed = []
        self.rows = [
            {"name": "search", "risk": "safe", "inputs": ["query"]},
            {"name": "open", "risk": "sensitive", "inputs": ["path"]},
            {"name": "never", "risk": "forbidden", "inputs": []},
        ]

    def list(self):
        return list(self.rows)

    def execute(self, name, **arguments):
        self.executed.append(name)
        return type("Result", (), {"success": True, "message": "ok", "data": {"ok": True}, "skill": name, "fallback_used": None})()


class CanonicalMissionTests(unittest.TestCase):
    def make_engine(self, authorize=None):
        root = Path(tempfile.mkdtemp())
        return MissionEngine(MissionStore(root / "missions.db"), authorize=authorize, catalog=MissionToolCatalogAdapter(_Registry()))

    def test_validator_uses_catalog_and_rejects_forbidden_and_cycles(self):
        planner = MissionPlanner(MissionToolCatalogAdapter(_Registry()))
        plan = planner.plan("find", {"steps": [{"id": "s", "action": "search", "arguments": {"query": "x"}}]})
        self.assertEqual(plan.steps[0].risk, "safe")
        with self.assertRaises(ValueError):
            planner.plan("bad", {"steps": [{"id": "x", "action": "never"}]})
        with self.assertRaises(ValueError):
            planner.plan("cycle", {"steps": [{"id": "a", "action": "search", "dependencies": ["b"]}, {"id": "b", "action": "search", "dependencies": ["a"]}]})

    def test_dynamic_reference_only_reads_completed_dependency(self):
        engine = self.make_engine()
        seen = []
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [
            {"id": "search", "action": "search", "arguments": {"query": "report"}, "expected": {"found": True}},
            {"id": "open", "action": "open", "dependencies": ["search"], "arguments": {"path": {"$ref": {"step": "search", "path": "data.path"}}}, "expected": {"opened": True}},
        ]})
        result = engine.run_plan(plan, executor=lambda action, args: (seen.append((action, args)) or ({"success": True, "observed": {"found": True}, "data": {"path": "x"}} if action == "search" else {"success": True, "observed": {"opened": True}})))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(seen[1][1]["path"], "x")

    def test_runtime_confirmation_waits_and_resume_keeps_identity(self):
        engine = self.make_engine()
        calls = []
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [{"id": "open", "action": "open", "arguments": {"path": "x"}, "expected": {"opened": True}}]})
        first = engine.run_plan(plan, executor=lambda action, args: {"requires_confirmation": True, "message": "confirm"})
        self.assertEqual(first["status"], "waiting_user")
        mission_id = first["id"]
        resumed = engine.resume(mission_id, executor=lambda action, args: (calls.append(action) or {"success": True, "observed": {"opened": True}}), confirmed_steps={"open"})
        self.assertEqual(resumed["id"], mission_id)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(calls, ["open"])

    def test_reference_failure_never_sends_placeholder(self):
        engine = self.make_engine()
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("bad", {"steps": [
            {"id": "open", "action": "open", "dependencies": ["search"], "arguments": {"path": {"$ref": {"step": "search", "path": "missing"}}}},
            {"id": "search", "action": "search", "arguments": {"query": "x"}},
        ]})
        seen = []
        result = engine.run_plan(plan, executor=lambda action, args: (seen.append(action) or {"success": True}))
        self.assertNotIn("open", seen)
        self.assertNotEqual(result["status"], "completed")

    def test_mission_store_plan_is_redacted_and_bounded(self):
        store = MissionStore(Path(tempfile.mkdtemp()) / "missions.db")
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("safe", {"steps": [{"id": "s", "action": "search", "arguments": {"query": "password=hidden"}}]})
        mission_id = store.create("safe", MissionEngine(store).build([]), plan.as_dict())
        record = store.get(mission_id)
        self.assertNotIn("hidden", str(record["plan"]))

    def test_preflight_checkpoint_and_resume_same_id(self):
        engine = self.make_engine(authorize=lambda action, args, risk: "confirm")
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [{"id": "open", "action": "open", "arguments": {"path": "x"}}]})
        first = engine.run_plan(plan, executor=lambda action, args: {"success": True, "observed": {}})
        self.assertEqual(first["checkpoint"]["confirmation_mode"], "preflight")
        resumed = engine.resume_preflight(first["id"], "open", executor=lambda action, args: {"success": True, "observed": {}})
        self.assertEqual(resumed["id"], first["id"])

    def test_late_confirmation_ingest_is_exactly_once(self):
        engine = self.make_engine()
        calls = []
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [{"id": "open", "action": "open", "arguments": {"path": "x"}, "expected": {"opened": True}}]})
        first = engine.run_plan(plan, executor=lambda action, args: {"richiede_conferma": True, "azione_id": "a1"})
        final = engine.accept_confirmed_result(first["id"], "open", {"success": True, "observed": {"opened": True}}, executor=lambda action, args: calls.append(action))
        self.assertEqual(final["status"], "completed")
        self.assertEqual(calls, [])

    def test_explicit_unverified_confirmation_stays_conservative(self):
        engine = self.make_engine()
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [{"id": "open", "action": "open", "arguments": {"path": "x"}}]})
        first = engine.run_plan(plan, executor=lambda action, args: {"requires_confirmation": True, "action_id": "a2"})
        final = engine.accept_confirmed_result(first["id"], "open", {"success": True, "verification": {"status": "unverified", "strength": 0.2}}, executor=lambda action, args: None)
        self.assertEqual(final["status"], "needs_verification")

    def test_explicit_verification_overrides_permissive_verifier(self):
        from jarvis_missions.evidence import Evidence, EvidenceEngine
        evidence = EvidenceEngine()
        evidence.register("open", lambda expected, result: Evidence("bad", True, 1.0, "permissive", ""))
        self.assertFalse(evidence.verify("open", {}, {"verification": {"status": "unverified", "strength": 0.2}}).verified)

    def test_cancel_by_id_stops_new_work(self):
        engine = self.make_engine()
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("open", {"steps": [{"id": "open", "action": "open", "arguments": {"path": "x"}}]})
        mission_id = engine.prepare(plan)
        cancelled = engine.cancel(mission_id)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_fallback_mapping_and_nested_risk_are_preserved(self):
        planner = MissionPlanner(MissionToolCatalogAdapter(_Registry()))
        plan = planner.plan("fallback", {"steps": [{"id": "s", "action": "search", "fallbacks": [{"action": "open", "arguments": {"path": "x"}, "risk": "sensitive"}]}]})
        self.assertEqual(plan.steps[0].fallbacks[0]["arguments"], {"path": "x"})
        self.assertEqual(plan.steps[0].fallbacks[0]["risk"], "sensitive")

    def test_current_manifest_risk_cannot_be_lowered_by_plan(self):
        planner = MissionPlanner(MissionToolCatalogAdapter(_Registry()))
        plan = planner.plan("risk", {"steps": [{"id": "s", "action": "open", "risk": "safe", "arguments": {"path": "x"}}]})
        self.assertEqual(plan.steps[0].risk, "sensitive")

    def _worker_bridge(self, engine, pending, confirmed):
        import brain
        import main

        class Runtime:
            missions = engine
            skills = engine.catalog.registry
            orchestrator = None

        worker = main.JarvisWorker.__new__(main.JarvisWorker)
        worker._risposta_locale = lambda message: None
        return worker, patch.object(main, "CORE_RUNTIME", Runtime()), patch.object(brain, "pending_confirmation_actions", lambda: pending), patch.object(brain, "conferma_ultima_azione", lambda: confirmed), patch.object(brain, "messaggio_risultato_operativo", lambda result: "ok")

    def test_main_preflight_confirmation_e2e(self):
        engine = self.make_engine(authorize=lambda action, args, risk: "confirm" if action == "open" else "allow")
        calls = []
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("flow", {"steps": [
            {"id": "a", "action": "search", "arguments": {"query": "x"}, "expected": {"ok": True}},
            {"id": "b", "action": "open", "dependencies": ["a"], "arguments": {"path": "x"}, "expected": {"ok": True}},
            {"id": "c", "action": "search", "dependencies": ["b"], "arguments": {"query": "y"}, "expected": {"ok": True}},
        ]})
        result = engine.run_plan(plan, executor=lambda action, args: (calls.append(action) or {"success": True, "observed": {"ok": True}}))
        worker, *patches = self._worker_bridge(engine, [], {})
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))
        self.assertEqual(result["id"], engine.store.recent(1)[0]["id"])
        self.assertEqual(calls, ["search"])
        self.assertEqual(engine.store.get(result["id"])["status"], "completed")
        self.assertEqual(engine.catalog.registry.executed, ["open", "search"])

    def test_main_executor_pending_confirmation_e2e_once(self):
        engine = self.make_engine()
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("late", {"steps": [{"id": "b", "action": "open", "arguments": {"path": "x"}, "expected": {"ok": True}}]})
        calls = []
        first = engine.run_plan(plan, executor=lambda action, args: {"richiede_conferma": True, "azione_id": "late-1"})
        worker, *patches = self._worker_bridge(engine, [{"action_id": "late-1"}], {"success": True, "observed": {"ok": True}})
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))
        self.assertEqual(first["id"], engine.store.recent(1)[0]["id"])
        self.assertEqual(calls, [])

    def test_main_ambiguous_pending_is_not_selected(self):
        engine = self.make_engine()
        worker, *patches = self._worker_bridge(engine, [{"action_id": "a"}, {"action_id": "b"}], {})
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))


if __name__ == "__main__":
    unittest.main()
