import tempfile,unittest
from pathlib import Path
from jarvis_missions import MissionEngine,MissionStore,StepSpec

class ExplainModeTests(unittest.TestCase):
    def setUp(self):self.store=MissionStore(Path(tempfile.mkdtemp())/"missions.db");self.engine=MissionEngine(self.store)
    def tearDown(self):self.engine.shutdown()
    def test_no_mission_is_explained_honestly(self):self.assertFalse(self.engine.explain()["success"])
    def test_latest_mission_exposes_task_status_progress_and_events(self):
        self.engine.register_action("ok",lambda:{"success":True,"observed":{"done":True}});mission=self.engine.run("Prepara progetto",[StepSpec("one","Crea cartella","ok",{}, {"done":True})])
        result=self.engine.explain(mission["id"]);self.assertTrue(result["success"]);self.assertEqual(result["data"]["task"],"Prepara progetto");self.assertEqual(result["data"]["progress"],{"completed":1,"total":1});self.assertTrue(result["data"]["recent_events"])

if __name__=="__main__":unittest.main()
