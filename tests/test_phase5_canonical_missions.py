import tempfile
import unittest
from pathlib import Path

from jarvis_missions.engine import MissionEngine
from jarvis_missions.planner import MissionPlanner, MissionToolCatalogAdapter
from jarvis_missions.store import MissionStore


class _Registry:
    def __init__(self):
        self.rows = [
            {"name": "search", "risk": "safe", "inputs": ["query"]},
            {"name": "open", "risk": "sensitive", "inputs": ["path"]},
            {"name": "never", "risk": "forbidden", "inputs": []},
        ]

    def list(self):
        return list(self.rows)


class CanonicalMissionTests(unittest.TestCase):
    def make_engine(self, authorize=None):
        root = Path(tempfile.mkdtemp())
        return MissionEngine(MissionStore(root / "missions.db"), authorize=authorize)

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


if __name__ == "__main__":
    unittest.main()
