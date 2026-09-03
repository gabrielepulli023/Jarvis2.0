import unittest
from jarvis_companion import CompanionEngine,CompanionMode
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_voice import VoiceState

class Voice:
    state=VoiceState.IDLE
    def __init__(self):self.calls=[]
    def submit(self,message,**kwargs):self.calls.append(message);return "id"

class CopilotModeTests(unittest.TestCase):
    def test_coding_copilot_detects_build_traceback_immediately(self):
        bus=EventBus();voice=Voice();engine=CompanionEngine(bus,StateManager(bus),voice,config={"mode":"coding_copilot","speak_threshold":.5,"hud_threshold":.3});engine.start()
        bus.publish("build.failed",{"traceback":"ModuleNotFoundError: package"},source="developer",confidence=.95)
        self.assertTrue(voice.calls);self.assertEqual(engine.snapshot()["mode"],CompanionMode.CODING_COPILOT.value);engine.stop()
    def test_do_not_disturb_suppresses_even_relevant_coding_event(self):
        bus=EventBus();voice=Voice();engine=CompanionEngine(bus,StateManager(bus),voice,config={"mode":"do_not_disturb","coding_enabled":True});engine.start()
        bus.publish("traceback.detected",{"traceback":"RuntimeError"},confidence=1);self.assertFalse(voice.calls);engine.stop()
    def test_trading_mode_recognizes_tradingview_without_order_execution(self):
        bus=EventBus();voice=Voice();decisions=[];bus.subscribe("companion.decision",decisions.append);engine=CompanionEngine(bus,StateManager(bus),voice,config={"mode":"trading_copilot"});engine.start()
        bus.publish("browser.changed",{"url":"https://tradingview.com/chart"},source="browser");self.assertTrue(decisions);self.assertEqual(decisions[-1].payload["category"],"trading");engine.stop()

if __name__=="__main__":unittest.main()
