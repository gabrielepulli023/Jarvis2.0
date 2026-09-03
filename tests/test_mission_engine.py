import tempfile,time,unittest
from pathlib import Path
from jarvis_missions import CancellationToken, MissionEngine, MissionStore, StepSpec
from jarvis_memory import MemoryStore
from jarvis_core.events import EventBus
from jarvis_core.recovery import RecoveryEngine, RecoveryPolicy

class MissionEngineTests(unittest.TestCase):
    def setUp(self):
        path=Path(tempfile.gettempdir())/"jarvis_engine_test.db"; path.unlink(missing_ok=True)
        self.engine=MissionEngine(MissionStore(path))
    def tearDown(self):self.engine.shutdown()
    def test_executes_dependencies_and_requires_evidence(self):
        calls=[]
        self.engine.register_action("observe",lambda value:(calls.append(value) or {"successo":True,"observed":{"value":value}}))
        mission=self.engine.run("goal",[
            StepSpec("a","first","observe",{"value":1},{"value":1}),
            StepSpec("b","second","observe",{"value":2},{"value":2},frozenset({"a"}))])
        self.assertEqual(mission["status"],"completed");self.assertEqual(calls,[1,2]);self.assertEqual(mission["graph"]["progress"],1.0)
    def test_unverified_result_retries_then_fails(self):
        attempts=[];self.engine.register_action("observe",lambda:(attempts.append(1) or {"successo":True,"observed":{"value":"wrong"}}))
        mission=self.engine.run("goal",[StepSpec("a","verify","observe",{}, {"value":"right"},max_attempts=2)])
        self.assertEqual(mission["status"],"failed");self.assertEqual(len(attempts),2)
    def test_timeout_is_bounded(self):
        self.engine.register_action("slow",lambda:(time.sleep(.2) or {"successo":True}))
        started=time.perf_counter();mission=self.engine.run("goal",[StepSpec("a","slow","slow",{}, {},timeout=.02,max_attempts=1)])
        self.assertLess(time.perf_counter()-started,.15);self.assertEqual(mission["status"],"failed")
    def test_pre_cancelled_mission_never_executes(self):
        token=CancellationToken();token.cancel();calls=[];self.engine.register_action("x",lambda:(calls.append(1) or {"successo":True}))
        mission=self.engine.run("goal",[StepSpec("a","x","x",{}, {})],token);self.assertEqual(mission["status"],"cancelled");self.assertFalse(calls)
    def test_completed_mission_becomes_procedural_memory(self):
        memory_path=Path(tempfile.gettempdir())/"jarvis_engine_memory.db";memory_path.unlink(missing_ok=True)
        self.engine.memory=MemoryStore(memory_path);self.engine.register_action("observe",lambda:{"successo":True,"observed":{"ok":True}})
        self.engine.run("repeatable goal",[StepSpec("a","observe","observe",{}, {"ok":True})])
        rows=self.engine.memory.search("observe",kind="procedural");self.assertEqual(rows[0]["metadata"]["objective"],"repeatable goal")
    def test_dry_run_records_plan_without_execution(self):
        calls=[];self.engine.register_action("x",lambda:(calls.append(1) or {"successo":True}))
        mission=self.engine.run("goal",[StepSpec("a","x","x",{}, {})],dry_run=True)
        self.assertEqual(mission["status"],"dry_run");self.assertFalse(calls);self.assertEqual(mission["checkpoint"]["steps"][0]["action"],"x")
    def test_sensitive_step_waits_for_explicit_confirmation(self):
        engine=MissionEngine(self.engine.store,authorize=lambda *_:"confirm");calls=[];engine.register_action("x",lambda:(calls.append(1) or {"successo":True}))
        mission=engine.run("goal",[StepSpec("a","x","x",{}, {},risk="admin")]);engine.shutdown()
        self.assertEqual(mission["status"],"waiting_user");self.assertFalse(calls)
    def test_fallback_recovery_verifies_and_completes(self):
        recovery=RecoveryEngine(EventBus(),RecoveryPolicy(max_retries=0,action_timeout=.2,global_timeout=1))
        engine=MissionEngine(self.engine.store,recovery=recovery);engine.register_action("bad",lambda:{"successo":True,"observed":{"ok":False}});engine.register_action("good",lambda:{"successo":True,"observed":{"ok":True}})
        mission=engine.run("goal",[StepSpec("a","x","bad",{}, {"ok":True},max_attempts=1,fallbacks=("good",))]);engine.shutdown();recovery.shutdown()
        self.assertEqual(mission["status"],"completed");self.assertEqual(mission["graph"]["tasks"][0]["result"]["observed"]["ok"],True)
    def test_failure_rolls_back_completed_steps(self):
        calls=[];self.engine.register_action("ok",lambda:{"successo":True,"observed":{"ok":True}});self.engine.register_action("bad",lambda:{"successo":False});self.engine.register_action("undo",lambda:(calls.append("undo") or {"successo":True}))
        mission=self.engine.run("goal",[StepSpec("a","first","ok",{}, {"ok":True},rollback_action="undo"),StepSpec("b","second","bad",{}, {},frozenset({"a"}),max_attempts=1)])
        self.assertEqual(mission["status"],"failed");self.assertEqual(calls,["undo"]);self.assertTrue(mission["checkpoint"]["rollback"][0]["success"])

if __name__=="__main__":unittest.main()
