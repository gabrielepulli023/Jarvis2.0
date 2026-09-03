import unittest
from jarvis_core.events import EventBus
from jarvis_system import HardwareEventMonitor,SystemInformation

class HardwareSystemTests(unittest.TestCase):
    def test_system_information_has_real_bounded_categories(self):
        data=SystemInformation().snapshot();self.assertTrue({"platform","cpu","memory","storage","uptime_seconds","audio_devices"}<=data.keys());self.assertGreater(data["memory"]["total"],0)
    def test_monitor_emits_device_and_network_diffs(self):
        states=iter([{"devices":[],"network":{"wifi":False}},{"devices":[("E:","E:\\")],"network":{"wifi":True}}])
        bus=EventBus();events=[];bus.subscribe("*",events.append);monitor=HardwareEventMonitor(bus,probe=lambda:next(states))
        monitor.check_once();monitor.check_once();topics=[event.topic for event in events]
        self.assertIn("device.connected",topics);self.assertIn("network.changed",topics)

if __name__=="__main__":unittest.main()
