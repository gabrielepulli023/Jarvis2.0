import unittest
from unittest.mock import Mock, patch
from jarvis_perception.state import PerceptionEngine,fuse_states,normalize_dom,normalize_uia,normalize_vision

class PerceptionTests(unittest.TestCase):
    def test_prefers_dom_and_avoids_expensive_fallbacks(self):
        calls=[];engine=PerceptionEngine()
        engine.register("vision",100,lambda:(calls.append("vision") or {"successo":True,"dati":{}}),normalize_vision)
        engine.register("uia",200,lambda:(calls.append("uia") or {"successo":True,"dati":{}}),normalize_uia)
        engine.register("dom",300,lambda:(calls.append("dom") or {"successo":True,"dati":{"title":"Page","elements":[]}}),normalize_dom)
        self.assertEqual(engine.observe().source,"dom");self.assertEqual(calls,["dom"])
    def test_falls_back_from_dom_to_uia(self):
        engine=PerceptionEngine();engine.register("dom",300,lambda:{"successo":False,"messaggio":"offline"},normalize_dom)
        engine.register("uia",200,lambda:{"successo":True,"dati":{"window":"Editor","elements":[]}},normalize_uia)
        self.assertEqual(engine.observe().source,"uia")
    def test_tracks_appeared_disappeared_and_changed_elements(self):
        states=iter([
            {"successo":True,"dati":{"title":"Page","elements":[{"id":"a","name":"Save","type":"button","enabled":True},{"id":"old","name":"Old","type":"text"}]}},
            {"successo":True,"dati":{"title":"Page","elements":[{"id":"a","name":"Save","type":"button","enabled":False},{"id":"new","name":"Done","type":"text"}]}}])
        engine=PerceptionEngine();engine.register("dom",1,lambda:next(states),normalize_dom);engine.observe();engine.observe();diff=engine.diff()
        self.assertEqual({x.id for x in diff.appeared},{"new"});self.assertEqual({x.id for x in diff.disappeared},{"old"});self.assertEqual(diff.changed[0][0].id,"a");self.assertTrue(diff.has_progress)
    def test_raises_with_observer_diagnostics(self):
        engine=PerceptionEngine();engine.register("dom",1,lambda:{"successo":False,"messaggio":"disconnected"},normalize_dom)
        with self.assertRaisesRegex(RuntimeError,"disconnected"):engine.observe()
    def test_dom_and_vision_fusion_reports_corroboration(self):
        dom=normalize_dom({"title":"Page","elements":[{"id":"save","name":"Save","type":"button"},{"id":"hidden","name":"Menu","type":"button"}]})
        vision=normalize_vision({"window":"Page","confidence":.8,"elements":[{"id":"v1","name":"Save","type":"text","confidence":.9}]})
        fused=fuse_states(dom,vision);self.assertEqual(fused.corroborated_ids,("save",));self.assertTrue(any("Menu" in x for x in fused.discrepancies));self.assertGreater(fused.confidence,.7)
    def test_adaptive_polling_reuses_state_until_due(self):
        observer=Mock(return_value={"successo":True,"dati":{"title":"Page","elements":[]}})
        engine=PerceptionEngine(active_interval=.1,idle_interval=10);engine.register("dom",1,observer,normalize_dom)
        first=engine.observe_if_due();second=engine.observe_if_due()
        self.assertIs(first,second);self.assertEqual(observer.call_count,1)
        engine.notify_activity()
        with patch("jarvis_perception.state.time.monotonic",return_value=engine._last_observed+.2):engine.observe_if_due()
        self.assertEqual(observer.call_count,2)

if __name__=="__main__":unittest.main()
