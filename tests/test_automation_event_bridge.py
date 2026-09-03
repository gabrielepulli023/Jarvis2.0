import tempfile,time,unittest
from pathlib import Path
from jarvis_automation import AutomationEngine
from jarvis_core.events import EventBus

class AutomationEventBridgeTests(unittest.TestCase):
    def test_event_bus_trigger_dispatches_off_publisher_thread(self):
        calls=[];engine=AutomationEngine(Path(tempfile.mkdtemp())/"automation.db",lambda action:(calls.append(action) or {"success":True}));bus=EventBus();engine.bind(bus)
        engine.create("network","event","network.connected",[{"skill":"network.adapters"}],retries=0);bus.publish("network.connected",{"name":"wifi"},source="hardware")
        deadline=time.monotonic()+2
        while not calls and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(calls,[{"skill":"network.adapters"}]);engine.close()
    def test_internal_automation_events_do_not_recurse(self):
        engine=AutomationEngine(Path(tempfile.mkdtemp())/"automation.db",lambda action:{"success":True});bus=EventBus();engine.bind(bus);engine.create("loop","event","automation.command",[{"command":"x"}],retries=0)
        bus.publish("automation.command",{"command":"x"},source="automation");time.sleep(.05);self.assertFalse(engine.history());engine.close()
    def test_event_worker_can_be_recovered_by_watchdog(self):
        engine=AutomationEngine(Path(tempfile.mkdtemp())/"automation.db",lambda action:{"success":True});bus=EventBus();engine.bind(bus);self.assertTrue(engine.healthy());engine.close();self.assertFalse(engine.healthy());self.assertTrue(engine.restart_events());engine.close()
    def test_malformed_event_name_is_normalized_without_crashing(self):
        engine=AutomationEngine(Path(tempfile.mkdtemp())/"automation.db",lambda action:{"success":True})
        self.assertEqual(engine.handle_event(None), [])
        self.assertEqual(engine.handle_event(123), [])
        engine.close()

if __name__=="__main__":unittest.main()
