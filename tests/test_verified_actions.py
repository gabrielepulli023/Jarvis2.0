import unittest
from jarvis_perception import PerceptionEngine,VerifiedActionRunner
from jarvis_perception.state import normalize_dom

class VerifiedActionTests(unittest.TestCase):
    @staticmethod
    def engine(states):
        iterator=iter(states);engine=PerceptionEngine();engine.register("dom",1,lambda:next(iterator),normalize_dom);return engine
    def test_accepts_action_only_after_observed_change(self):
        states=[{"successo":True,"dati":{"title":"A","elements":[]}},{"successo":True,"dati":{"title":"A","elements":[{"id":"done","name":"Done","type":"text"}]}}]
        runner=VerifiedActionRunner(self.engine(states));result=runner.run("click",{},[("uia",lambda:{"successo":True})],verification_timeout=.1)
        self.assertTrue(result.success);self.assertEqual(result.strategy,"uia");self.assertTrue(result.diff.has_progress)
    def test_uses_next_strategy_when_first_fails(self):
        states=[{"successo":True,"dati":{"title":"A","elements":[]}},{"successo":True,"dati":{"title":"A","elements":[{"id":"x","name":"X","type":"text"}]}}]
        runner=VerifiedActionRunner(self.engine(states));result=runner.run("act",{},[("api",lambda:{"successo":False,"messaggio":"no"}),("uia",lambda:{"successo":True})],verification_timeout=.1)
        self.assertTrue(result.success);self.assertEqual([x.strategy for x in result.attempts],["api","uia"])
    def test_custom_expected_condition_can_verify_stable_state(self):
        states=[{"successo":True,"dati":{"title":"A","elements":[]}},{"successo":True,"dati":{"title":"A","elements":[]}}]
        runner=VerifiedActionRunner(self.engine(states));result=runner.run("focus",{},[("uia",lambda:{"successo":True,"focused":True})],expected=lambda state,diff,action:action.get("focused") is True,verification_timeout=.1)
        self.assertTrue(result.success)
    def test_anti_loop_stops_repeated_unverified_action(self):
        state={"successo":True,"dati":{"title":"A","elements":[]}}
        engine=PerceptionEngine();engine.register("dom",1,lambda:state,normalize_dom);runner=VerifiedActionRunner(engine,anti_loop_limit=2)
        for _ in range(2):self.assertFalse(runner.run("click",{"x":1},[("mouse",lambda:{"successo":True})],verification_timeout=.06).success)
        third=runner.run("click",{"x":1},[("mouse",lambda:{"successo":True})]);self.assertEqual(third.attempts[0].strategy,"anti_loop")

if __name__=="__main__":unittest.main()
