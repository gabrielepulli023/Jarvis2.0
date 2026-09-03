import os
import tempfile
import unittest
import time
from pathlib import Path


TEST_ROOT = Path(tempfile.gettempdir()) / "jarvis_core_tests"
os.environ["JARVIS_DATA_DIR"] = str(TEST_ROOT)


class PermissionTests(unittest.TestCase):
    def tearDown(self):
        import permission_manager as permissions
        permissions.clear_session()

    def test_modes_and_pin(self):
        import permission_manager as permissions
        permissions.STORE = TEST_ROOT / "permissions.json"
        permissions.STORE.unlink(missing_ok=True)
        permissions.set_mode("observe")
        self.assertEqual(permissions.profile()["mode"], "observe")
        self.assertEqual(permissions.decision("computer"), "deny")
        permissions.set_mode("assisted")
        self.assertTrue(permissions.set_pin("2468"))
        self.assertFalse(permissions.verify_pin("0000"))
        self.assertTrue(permissions.verify_pin("2468"))
        self.assertTrue(permissions.profile()["pin"])

    def test_session_permissions_override_global_permissions(self):
        import permission_manager as permissions
        permissions.activate_session("Ospite", "GUEST", {"computer": "allow", "admin": "deny"}, "face_rejected")
        self.assertEqual(permissions.decision("computer"), "allow")
        self.assertEqual(permissions.decision("admin"), "deny")
        permissions.activate_session("Gabriele", "CEO", {"admin": "allow"}, "voice_phrase")
        self.assertEqual(permissions.decision("admin"), "confirm")


class ScriptTests(unittest.TestCase):
    def test_static_guard(self):
        import script_engine
        self.assertTrue(script_engine.inspect_script("Write-Output 'ok'")["safe"])
        self.assertFalse(script_engine.inspect_script("Remove-Item C:\\ -Recurse")["safe"])
        self.assertFalse(script_engine.inspect_script("import subprocess\nsubprocess.run('x')")["safe"])


class IntelligenceLayerTests(unittest.TestCase):
    def test_async_io_lane_runs_tasks_concurrently(self):
        import async_engine
        engine = async_engine.AsyncEngine()
        started = time.perf_counter()
        _, first = engine.submit("io", time.sleep, 0.2)
        _, second = engine.submit("io", time.sleep, 0.2)
        first.result(timeout=2); second.result(timeout=2)
        elapsed = time.perf_counter() - started
        engine.shutdown()
        self.assertLess(elapsed, 0.36)

    def test_smart_cache_expires(self):
        import result_cache
        result_cache.clear()
        result_cache.put("x", {"value": 1}, ttl=0.1)
        self.assertEqual(result_cache.get("x")["value"], 1)
        time.sleep(0.12)
        self.assertIsNone(result_cache.get("x"))

    def test_simulation_never_executes_and_flags_protected_path(self):
        from simulation_engine import simulate_action
        result = simulate_action("elimina", {"percorso": "C:\\Windows\\System32"})
        self.assertFalse(result["dati"]["executed"])
        self.assertTrue(result["dati"]["warnings"])

    def test_repeated_success_becomes_learned_procedure(self):
        import adaptive_learning
        adaptive_learning.STORE = TEST_ROOT / "learned.json"
        adaptive_learning.STORE.unlink(missing_ok=True)
        mission = {"request": "apri e cerca", "status": "completed", "steps": [
            {"tool": "apri_programma", "arguments": {"nome": "Chrome"}, "success": True, "verification": {"status": "verified"}},
            {"tool": "cerca_google", "arguments": {"query": "test"}, "success": True, "verification": {"status": "verified"}},
        ]}
        adaptive_learning.learn_completed_mission(mission)
        learned = adaptive_learning.learn_completed_mission(mission)
        self.assertTrue(learned["ready_as_skill"])


class AgentStateTests(unittest.TestCase):
    def test_job_lifecycle(self):
        import agent_state
        agent_state.STORE = TEST_ROOT / "jobs.json"
        agent_state.STORE.unlink(missing_ok=True)
        job_id = agent_state.begin("prova")
        self.assertTrue(agent_state.add_step(job_id, "tool", {}, {"successo": True, "messaggio": "ok"}))
        self.assertTrue(agent_state.finish(job_id, "completed", "fatto"))
        latest = agent_state.recent(1)[0]
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(len(latest["steps"]), 1)

    def test_mission_has_plan_checkpoint_and_evidence(self):
        import agent_state
        agent_state.STORE = TEST_ROOT / "missions.json"
        agent_state.STORE.unlink(missing_ok=True)
        job_id = agent_state.begin("Apri Chrome e verifica la pagina")
        agent_state.add_step(job_id, "apri_programma", {"nome": "Chrome"}, {"successo": True, "messaggio": "Chrome aperto"})
        agent_state.finish(job_id, "completed", "Operazione completata")
        mission = agent_state.recent(1)[0]
        self.assertTrue(mission["plan"])
        self.assertEqual(mission["checkpoint"]["completed_steps"], 1)
        self.assertEqual(mission["steps"][0]["verification"]["status"], "verified")
        self.assertEqual(mission["status"], "completed")

    def test_interrupted_mission_is_resumable(self):
        import agent_state
        agent_state.STORE = TEST_ROOT / "paused_missions.json"
        agent_state.STORE.unlink(missing_ok=True)
        agent_state.begin("Crea un progetto completo")
        self.assertEqual(agent_state.recover_interrupted(), 1)
        mission = agent_state.latest_resumable()
        self.assertEqual(mission["status"], "paused")
        self.assertTrue(mission["resumable"])


if __name__ == "__main__":
    unittest.main()
