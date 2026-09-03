import tempfile, unittest
from pathlib import Path
from jarvis_missions import MissionStore, Task, TaskGraph, TaskStatus

class TaskGraphTests(unittest.TestCase):
    def test_dependencies_and_parallel_ready_tasks(self):
        graph=TaskGraph([Task("a","start"),Task("b","parallel one",{"a"}),Task("c","parallel two",{"a"})])
        self.assertEqual([x.id for x in graph.ready()],["a"]); graph.start("a"); graph.complete("a",{"ok":True},[{"kind":"assertion"}])
        self.assertEqual({x.id for x in graph.ready()},{"b","c"})
    def test_cycle_is_rejected(self):
        with self.assertRaises(ValueError): TaskGraph([Task("a","a",{"b"}),Task("b","b",{"a"})])
    def test_retry_limit_and_blocking(self):
        graph=TaskGraph([Task("a","unstable",max_attempts=2),Task("b","dependent",{"a"})])
        graph.start("a"); graph.fail("a","one"); self.assertEqual(graph.tasks["a"].status,TaskStatus.RETRY)
        graph.start("a"); graph.fail("a","two"); self.assertEqual(graph.tasks["a"].status,TaskStatus.FAILED); self.assertEqual(graph.tasks["b"].status,TaskStatus.BLOCKED)
    def test_completion_requires_evidence(self):
        graph=TaskGraph([Task("a","verify")]); graph.start("a")
        with self.assertRaises(ValueError): graph.complete("a",{"ok":True},[])
    def test_cancellation_propagates(self):
        graph=TaskGraph([Task("a","first"),Task("b","second",{"a"})]); graph.cancel()
        self.assertTrue(all(x.status==TaskStatus.CANCELLED for x in graph.tasks.values()))

class MissionStoreTests(unittest.TestCase):
    def test_persists_graph_checkpoint_and_event(self):
        path=Path(tempfile.gettempdir())/"jarvis_missions_v2_test.db"; path.unlink(missing_ok=True)
        store=MissionStore(path); graph=TaskGraph([Task("a","first")]); mission_id=store.create("objective",graph)
        graph.start("a"); graph.complete("a",{"ok":True},[{"path":"x"}]); store.save(mission_id,graph,status="completed",checkpoint={"last":"a"})
        loaded=store.get(mission_id); self.assertEqual(loaded["status"],"completed"); self.assertEqual(loaded["checkpoint"]["last"],"a"); self.assertEqual(loaded["graph"]["progress"],1.0)

if __name__=="__main__": unittest.main()
