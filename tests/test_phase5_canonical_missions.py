import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_missions.engine import MissionEngine, StepSpec
from jarvis_missions.planner import MissionPlanner, MissionToolCatalogAdapter
from jarvis_missions.store import MissionStore
from jarvis_core.events import EventBus
from jarvis_core.recovery import RecoveryEngine, RecoveryPolicy


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

    def test_nested_forbidden_validation_uses_declared_and_manifest_risk(self):
        planner = MissionPlanner(MissionToolCatalogAdapter(_Registry()))
        cases = [
            {"precondition": {"action": "search", "risk": "forbidden"}},
            {"fallbacks": [{"action": "search", "risk": "forbidden"}]},
            {"rollback": {"action": "search", "risk": "forbidden"}},
            {"precondition": {"action": "never"}},
            {"fallbacks": [{"action": "never"}]},
            {"rollback": {"action": "never"}},
        ]
        for nested in cases:
            with self.subTest(nested=nested), self.assertRaises(ValueError):
                planner.plan("nested-risk", {"steps": [{"id": "s", "action": "search", **nested}]})

    def test_precondition_nested_confirmation_bridge_exactly_once(self):
        engine = self.make_engine(authorize=lambda action, args, risk: "confirm" if action == "search" and risk == "sensitive" else "allow")
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("precondition", {"steps": [{
            "id": "s", "action": "open", "arguments": {"path": "x"}, "expected": {"ok": True},
            "precondition": {"action": "search", "arguments": {"query": "ready"}, "expected": {"ok": True}, "risk": "sensitive"},
        }]})
        first = engine.run_plan(plan, executor=lambda action, args: {"success": True, "observed": {"ok": True}})
        self.assertEqual(first["status"], "waiting_user")
        checkpoint = first["checkpoint"]
        self.assertEqual(checkpoint["nested_action"], "precondition")
        worker, *patches = self._worker_bridge(engine, [], {})
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertTrue(worker._comando_memoria_o_conferma("Confermo"))
        self.assertEqual(engine.catalog.registry.executed, ["search", "open"])
        self.assertEqual(engine.store.get(first["id"])["status"], "completed")
        self.assertEqual(checkpoint["mission_id"], first["id"])

    def test_sensitive_fallback_waits_then_executes_once_and_uses_f1_expected(self):
        recovery = RecoveryEngine(EventBus(), RecoveryPolicy(max_retries=0, action_timeout=.2, global_timeout=1))
        calls = []
        engine = MissionEngine(MissionStore(Path(tempfile.mkdtemp()) / "missions.db"), authorize=lambda action, args, risk: "confirm" if action == "f1" else "allow")
        engine.recovery = recovery
        engine.register_action("primary", lambda: {"successo": True, "observed": {"bad": True}})
        engine.register_action("f1", lambda: (calls.append("f1") or {"successo": True, "observed": {"one": True}}))
        engine.register_action("f2", lambda: (calls.append("f2") or {"successo": True, "observed": {"two": True}}))
        spec = __import__("jarvis_missions.engine", fromlist=["StepSpec"]).StepSpec(
            "s", "step", "primary", {}, {"done": True}, max_attempts=1,
            fallbacks=({"id": "F1", "action": "f1", "expected": {"one": True}, "risk": "sensitive"}, {"id": "F2", "action": "f2", "expected": {"two": True}}),
        )
        mission = engine.run("fallback", [spec], plan_payload={"objective": "fallback", "steps": [{"id": "s", "action": "primary", "expected": {"done": True}, "fallbacks": list(spec.fallbacks)}]})
        self.assertEqual(mission["status"], "waiting_user")
        self.assertEqual(calls, [])
        resumed = engine.resume_nested_confirmation(mission["id"], step_id="s", nested_action="fallback", action="f1", fallback_index=0, fallback_id="F1", executor=lambda action, args: (calls.append(action) or {"success": True, "observed": {"one": True}}))
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(calls, ["f1"])
        self.assertEqual(resumed["graph"]["tasks"][0]["evidence"][0]["expected"], "{'one': True}")
        recovery.shutdown()

    def test_sensitive_rollback_waits_and_keeps_failed_semantics(self):
        calls = []
        engine = MissionEngine(MissionStore(Path(tempfile.mkdtemp()) / "missions.db"), authorize=lambda action, args, risk: "confirm" if action == "undo" else "allow")
        engine.register_action("ok", lambda: {"successo": True, "observed": {"ok": True}})
        engine.register_action("bad", lambda: {"successo": False})
        engine.register_action("undo", lambda: (calls.append("undo") or {"successo": True}))
        from jarvis_missions.engine import StepSpec
        specs = [StepSpec("a", "ok", "ok", {}, {"ok": True}, rollback_action="undo", rollback_risk="sensitive"), StepSpec("b", "bad", "bad", {}, {}, frozenset({"a"}), max_attempts=1)]
        mission = engine.run("rollback", specs, plan_payload={"objective": "rollback", "steps": [{"id": "a", "action": "ok", "expected": {"ok": True}, "rollback": {"action": "undo", "risk": "sensitive"}}, {"id": "b", "action": "bad", "dependencies": ["a"], "max_attempts": 1}]})
        self.assertEqual(mission["status"], "waiting_user")
        self.assertEqual(calls, [])
        resumed = engine.resume_nested_confirmation(mission["id"], step_id="a", nested_action="rollback", action="undo", executor=lambda action, args: (calls.append(action) or {"success": True}))
        self.assertEqual(calls, ["undo"])
        self.assertEqual(resumed["status"], "failed")

    def test_cancelled_nested_confirmation_never_executes(self):
        calls = []
        engine = self.make_engine(authorize=lambda action, args, risk: "confirm" if action == "search" else "allow")
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("cancel", {"steps": [{"id": "s", "action": "open", "precondition": {"action": "search", "risk": "sensitive"}}]})
        mission = engine.run_plan(plan, executor=lambda action, args: (calls.append(action) or {"success": True, "observed": {"ok": True}}))
        engine.cancel(mission["id"])
        resumed = engine.resume_nested_confirmation(mission["id"], step_id="s", nested_action="precondition", action="search", executor=lambda action, args: calls.append(action))
        self.assertEqual(resumed["status"], "cancelled")
        self.assertEqual(calls, [])

    def test_precondition_current_deny_after_confirmation_never_executes(self):
        policy = {"value": "confirm"}
        engine = self.make_engine(authorize=lambda action, args, risk: policy["value"] if action == "search" else "allow")
        plan = MissionPlanner(MissionToolCatalogAdapter(_Registry())).plan("deny-pre", {"steps": [{"id": "s", "action": "open", "precondition": {"action": "search", "risk": "sensitive"}}]})
        first = engine.run_plan(plan, executor=lambda action, args: {"success": True, "observed": {"ok": True}})
        policy["value"] = "deny"
        resumed = engine.resume_nested_confirmation(first["id"], step_id="s", nested_action="precondition", action="search", executor=lambda action, args: (_ for _ in ()).throw(AssertionError("denied precondition executed")))
        self.assertNotEqual(resumed["status"], "completed")

    def test_fallback_current_deny_after_confirmation_never_executes(self):
        policy = {"value": "confirm"}
        engine = MissionEngine(MissionStore(Path(tempfile.mkdtemp()) / "missions.db"), authorize=lambda action, args, risk: policy["value"] if action == "f1" else "allow", recovery=RecoveryEngine(EventBus(), RecoveryPolicy(max_retries=0, action_timeout=.2, global_timeout=1)))
        nested_calls = []
        engine.register_action("primary", lambda: {"successo": True, "observed": {"bad": True}})
        engine.register_action("f1", lambda: (nested_calls.append("f1") or {"successo": True, "observed": {"one": True}}))
        spec = StepSpec("s", "step", "primary", {}, {"done": True}, max_attempts=1, fallbacks=({"id": "F1", "action": "f1", "expected": {"one": True}, "risk": "sensitive"},))
        first = engine.run("deny-fallback", [spec], plan_payload={"objective": "deny-fallback", "steps": [{"id": "s", "action": "primary", "max_attempts": 1, "expected": {"done": True}, "fallbacks": list(spec.fallbacks)}]})
        policy["value"] = "deny"
        resumed = engine.resume_nested_confirmation(first["id"], step_id="s", nested_action="fallback", action="f1", fallback_index=0, fallback_id="F1", executor=lambda action, args: (_ for _ in ()).throw(AssertionError("denied fallback executed")))
        self.assertNotEqual(resumed["status"], "completed")
        self.assertEqual(nested_calls, [])
        engine.recovery.shutdown()

    def test_rollback_current_deny_after_confirmation_never_executes(self):
        policy = {"value": "confirm"}
        engine = MissionEngine(MissionStore(Path(tempfile.mkdtemp()) / "missions.db"), authorize=lambda action, args, risk: policy["value"] if action == "undo" else "allow")
        calls = []
        engine.register_action("ok", lambda: {"successo": True, "observed": {"ok": True}})
        engine.register_action("bad", lambda: {"successo": False})
        engine.register_action("undo", lambda: (calls.append("undo") or {"successo": True}))
        specs = [StepSpec("a", "ok", "ok", {}, {"ok": True}, rollback_action="undo", rollback_risk="sensitive"), StepSpec("b", "bad", "bad", {}, {}, frozenset({"a"}), max_attempts=1)]
        first = engine.run("deny-rollback", specs, plan_payload={"objective": "deny-rollback", "steps": [{"id": "a", "action": "ok", "expected": {"ok": True}, "rollback": {"action": "undo", "risk": "sensitive"}}, {"id": "b", "action": "bad", "dependencies": ["a"], "max_attempts": 1}]})
        policy["value"] = "deny"
        resumed = engine.resume_nested_confirmation(first["id"], step_id="a", nested_action="rollback", action="undo", executor=lambda action, args: (_ for _ in ()).throw(AssertionError("denied rollback executed")))
        self.assertNotEqual(resumed["status"], "completed")
        self.assertEqual(calls, [])

    def test_two_sensitive_rollbacks_are_exactly_once_and_have_ledger(self):
        policy = {"value": "confirm"}
        store = MissionStore(Path(tempfile.mkdtemp()) / "missions.db")
        engine = MissionEngine(store, authorize=lambda action, args, risk: policy["value"] if action in {"undo_a", "undo_b"} else "allow")
        calls = []
        engine.register_action("ok_a", lambda: {"successo": True, "observed": {"ok": True}})
        engine.register_action("ok_b", lambda: {"successo": True, "observed": {"ok": True}})
        engine.register_action("bad", lambda: {"successo": False})
        engine.register_action("undo_a", lambda: {"success": True})
        engine.register_action("undo_b", lambda: {"success": True})
        specs = [
            StepSpec("a", "A", "ok_a", {}, {"ok": True}, rollback_action="undo_a", rollback_risk="sensitive"),
            StepSpec("b", "B", "ok_b", {}, {"ok": True}, frozenset({"a"}), rollback_action="undo_b", rollback_risk="sensitive"),
            StepSpec("c", "C", "bad", {}, {}, frozenset({"b"}), max_attempts=1),
        ]
        payload = {"objective": "multi-rollback", "steps": [{"id": "a", "action": "ok_a", "expected": {"ok": True}, "rollback": {"action": "undo_a", "risk": "sensitive"}}, {"id": "b", "action": "ok_b", "dependencies": ["a"], "expected": {"ok": True}, "rollback": {"action": "undo_b", "risk": "sensitive"}}, {"id": "c", "action": "bad", "dependencies": ["b"], "max_attempts": 1}]}
        first = engine.run("multi-rollback", specs, plan_payload=payload)
        self.assertEqual(first["status"], "waiting_user", repr(first))
        self.assertEqual(first["checkpoint"]["nested_action"], "rollback")
        self.assertEqual(first["checkpoint"]["step_id"], "b")
        def dispatch(action, args):
            calls.append(action)
            return {"success": True}
        second = engine.resume_nested_confirmation(first["id"], step_id="b", nested_action="rollback", action="undo_b", executor=dispatch)
        self.assertEqual(calls, ["undo_b"])
        self.assertEqual(second["status"], "waiting_user")
        self.assertEqual(second["checkpoint"]["step_id"], "a")
        self.assertEqual(second["checkpoint"]["rollback_completed"][0]["step_id"], "b")
        # A fresh engine models restart: B is read from MissionStore and is not rerun.
        restarted = MissionEngine(store, authorize=lambda action, args, risk: "confirm" if action == "undo_a" else "allow")
        final = restarted.resume_nested_confirmation(second["id"], step_id="a", nested_action="rollback", action="undo_a", executor=dispatch)
        self.assertEqual(calls, ["undo_b", "undo_a"])
        self.assertEqual(final["status"], "failed")
        self.assertEqual({row["step_id"] for row in final["checkpoint"]["rollback_completed"]}, {"a", "b"})

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
