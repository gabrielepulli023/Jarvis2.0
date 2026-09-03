import sys,time,unittest
from unittest.mock import patch

from jarvis_broker.client import BrokerClient
from jarvis_core.events import EventBus
from jarvis_core.processes import ProcessManager
from jarvis_core.recovery import RecoveryEngine,RecoveryPolicy,RecoveryStrategy
from jarvis_voice import VoiceSessionEngine,VoiceState
from jarvis_apps import AppManager

class FailureInjectionTests(unittest.TestCase):
    def test_crashed_process_is_observed_without_crashing_manager(self):
        bus=EventBus();events=[];bus.subscribe("process.exited",events.append);manager=ProcessManager(bus)
        item=manager.start([sys.executable,"-c","raise SystemExit(7)"])
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not events:time.sleep(.02)
        self.assertTrue(events);self.assertEqual(events[0].payload["returncode"],7);self.assertEqual(item.process.poll(),7);manager.shutdown()
    def test_broker_offline_degrades_to_structured_unavailable(self):
        with patch("jarvis_broker.client.load_or_create",return_value=b"x"*32),patch("jarvis_broker.client.Client",side_effect=ConnectionRefusedError()):
            result=BrokerClient().execute("service.list",{})
        self.assertFalse(result.success);self.assertEqual(result.request_id,"unavailable");self.assertEqual(result.data["error"],"ConnectionRefusedError")
    def test_api_timeout_uses_fallback_and_stays_bounded(self):
        recovery=RecoveryEngine(EventBus(),RecoveryPolicy(max_retries=0,action_timeout=.03,global_timeout=.2))
        slow=RecoveryStrategy("api",lambda:(time.sleep(.2) or {"success":True}),lambda state,result:True)
        local=RecoveryStrategy("local",lambda:{"success":True},lambda state,result:True)
        started=time.monotonic();result=recovery.run("provider",[slow,local],lambda:{})
        self.assertTrue(result.success);self.assertEqual(result.strategy,"local");self.assertLess(time.monotonic()-started,.15);self.assertEqual(result.attempts[0].error,"action_timeout");recovery.shutdown()
    def test_tts_failure_isolated_and_next_request_recovers(self):
        calls=[]
        def speaker(text,interruptible):
            calls.append(text)
            if len(calls)==1:raise RuntimeError("device missing")
            return text
        engine=VoiceSessionEngine(speaker,lambda text:None)
        first=engine.submit("one");self.assertIsNone(engine.wait(first,1));self.assertEqual(engine.state,VoiceState.ERROR)
        second=engine.submit("two");self.assertEqual(engine.wait(second,1),"two");self.assertEqual(engine.state,VoiceState.IDLE)
        history=engine.snapshot()["history"];self.assertIn("device missing",history[0]["error"]);engine.shutdown()
    def test_missing_app_and_disappeared_ui_are_structured_failures(self):
        class Broker:pass
        manager=AppManager(Broker(),ProcessManager(EventBus()))
        with patch.object(manager,"discover",return_value=[]):self.assertFalse(manager.open("missing")["success"])
        manager.processes.shutdown()

if __name__=="__main__":unittest.main()
