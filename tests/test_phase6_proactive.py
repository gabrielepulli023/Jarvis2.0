import json
import tempfile
import threading
import unittest
from pathlib import Path

from jarvis_companion import CompanionEngine, InterventionCandidate
from jarvis_core.events import EventBus
from jarvis_core.state import StateManager
from jarvis_system import NotificationCenter
from proactive import SystemSignalMonitor
from jarvis_voice import VoiceState
from settings_store import get_setting, set_setting


class Voice:
    state = VoiceState.IDLE
    def __init__(self): self.calls = []
    def submit(self, text, priority, interruptible): self.calls.append(text); return "id"


class Phase6Tests(unittest.TestCase):
    def setUp(self):
        self._incidents_before = get_setting("system_signal_incidents", {})
        set_setting("system_signal_incidents", {})

    def tearDown(self):
        set_setting("system_signal_incidents", self._incidents_before)

    def make(self, context_provider=None, **config):
        bus = EventBus(); state = StateManager(bus); voice = Voice(); notes = NotificationCenter(bus)
        with tempfile.TemporaryDirectory() as directory:
            engine = CompanionEngine(bus, state, voice, config={"mode": "companion", **config},
                                     notifications=notes, context_provider=context_provider,
                                     persistence_path=Path(directory) / "preferences.json")
            engine.start()
            yield engine, bus, voice, notes
            engine.stop()

    def test_system_threshold_and_hysteresis(self):
        bus = EventBus(); received = []; bus.subscribe("system.memory_pressure", received.append)
        values = iter(({"memory_percent": 89, "disk_percent": 1, "battery_percent": None, "battery_plugged": None},
                       {"memory_percent": 91, "disk_percent": 1, "battery_percent": None, "battery_plugged": None},
                       {"memory_percent": 89, "disk_percent": 1, "battery_percent": None, "battery_plugged": None},
                       {"memory_percent": 91, "disk_percent": 1, "battery_percent": None, "battery_plugged": None}))
        monitor = SystemSignalMonitor(bus, probe=lambda: next(values))
        for _ in range(4): monitor.check_once()
        self.assertEqual(len(received), 1)

    def test_memory_incident_latch_recovery_and_rearm(self):
        settings = {"system_signal_incidents": {}}
        def get(key, default=None): return settings.get(key, default)
        def put(key, value): settings[key] = value
        bus = EventBus(); alerts = []; recovered = []
        bus.subscribe("system.memory_pressure", alerts.append); bus.subscribe("system.memory_critical", alerts.append)
        bus.subscribe("system.memory_recovered", recovered.append)
        values = iter((89, 91, 92, 95, 96, 98, 99, 94, 98, 87, 90, 87, 87, 87, 92))
        monitor = SystemSignalMonitor(bus, probe=lambda: {"memory_percent": next(values), "disk_percent": 1, "battery_percent": None, "battery_plugged": None}, settings_get=get, settings_set=put)
        for _ in range(15): monitor.check_once()
        self.assertEqual(len(alerts), 2)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].payload["value"], 87)
        self.assertEqual(recovered[0].payload["metric"], "memory_percent")
        self.assertNotEqual(alerts[0].payload["incident_id"], alerts[1].payload["incident_id"])

    def test_memory_persistence_survives_monitor_restart_without_realert(self):
        settings = {"system_signal_incidents": {}}
        def get(key, default=None): return settings.get(key, default)
        def put(key, value): settings[key] = value
        bus = EventBus(); alerts = []; bus.subscribe("system.memory_pressure", alerts.append)
        first = SystemSignalMonitor(bus, probe=lambda: {"memory_percent": 96, "disk_percent": 1, "battery_percent": None, "battery_plugged": None}, settings_get=get, settings_set=put)
        first.check_once(); first.stop()
        second = SystemSignalMonitor(bus, probe=lambda: {"memory_percent": 95, "disk_percent": 1, "battery_percent": None, "battery_plugged": None}, settings_get=get, settings_set=put)
        second.check_once()
        self.assertEqual(len(alerts), 1)
        self.assertTrue(second._memory_incident["active"])

    def test_repeated_memory_critical_checks_emit_one_initial_event(self):
        settings = {"system_signal_incidents": {}}
        bus = EventBus(); seen = []
        bus.subscribe("system.memory_critical", seen.append)
        monitor = SystemSignalMonitor(
            bus, probe=lambda: {"memory_percent": 99, "disk_percent": 1, "battery_percent": None, "battery_plugged": None},
            settings_get=lambda key, default=None: settings.get(key, default),
            settings_set=lambda key, value: settings.__setitem__(key, value),
        )
        for _ in range(1000):
            monitor.check_once()
        self.assertEqual(len(seen), 1)

    def test_legacy_worker_has_no_memory_alert_side_channel(self):
        source = Path("proactive.py").read_text(encoding="utf-8")
        worker = source.split("class ProactiveMonitorWorker", 1)[1]
        self.assertNotIn("virtual_memory", worker)

    def test_recovery_message_contains_current_percentage_and_incident_fingerprint(self):
        bus = EventBus(); state = StateManager(bus); voice = Voice()
        with tempfile.TemporaryDirectory() as directory:
            engine = CompanionEngine(bus, state, voice, config={"mode": "normal"}, persistence_path=Path(directory) / "preferences.json")
            event = bus.publish("system.memory_recovered", {"metric": "memory_percent", "value": 74, "incident_id": "memory-2"}, source="system_signals")
            candidate = engine._candidate_from(event)
            self.assertIn("74%", candidate.message)
            self.assertEqual(candidate.category, "system")
            self.assertIn("memory-2", candidate.fingerprint)

    def test_memory_alert_messages_contain_clamped_integer_percentage(self):
        bus = EventBus(); state = StateManager(bus); voice = Voice()
        with tempfile.TemporaryDirectory() as directory:
            engine = CompanionEngine(bus, state, voice, persistence_path=Path(directory) / "preferences.json")
            pressure = engine._candidate_from(bus.publish(
                "system.memory_pressure", {"value": 92}, source="system_signals"))
            critical = engine._candidate_from(bus.publish(
                "system.memory_critical", {"value": 98}, source="system_signals"))
            recovered = engine._candidate_from(bus.publish(
                "system.memory_recovered", {"value": 74}, source="system_signals"))
            self.assertIn("92%", pressure.message)
            self.assertIn("98%", critical.message)
            self.assertIn("74%", recovered.message)

    def test_memory_alert_percentage_conversion_is_fail_safe_and_clamped(self):
        bus = EventBus(); state = StateManager(bus); voice = Voice()
        with tempfile.TemporaryDirectory() as directory:
            engine = CompanionEngine(bus, state, voice, persistence_path=Path(directory) / "preferences.json")
            for value, expected in (("bad", "0%"), (float("nan"), "0%"), (-5, "0%"), (125, "100%")):
                candidate = engine._candidate_from(bus.publish(
                    "system.memory_pressure", {"value": value}, source="system_signals"))
                self.assertIn(expected, candidate.message)

    def test_startup_critical_and_exclusive_severity(self):
        for field, topic in (("battery_percent", "system.battery_critical"), ("memory_percent", "system.memory_critical"), ("disk_percent", "system.disk_critical")):
            bus = EventBus(); seen = []; bus.subscribe(topic, seen.append)
            base = {"memory_percent": 1, "disk_percent": 1, "battery_percent": None, "battery_plugged": False}
            base[field] = 4 if field == "battery_percent" else 99
            SystemSignalMonitor(bus, probe=lambda base=base: base).check_once()
            self.assertEqual(len(seen), 1)

        set_setting("system_signal_incidents", {})
        bus = EventBus(); pressure = []; critical = []
        bus.subscribe("system.memory_pressure", pressure.append); bus.subscribe("system.memory_critical", critical.append)
        values = iter(({"memory_percent": 89, "disk_percent": 1, "battery_percent": None, "battery_plugged": None},
                       {"memory_percent": 99, "disk_percent": 1, "battery_percent": None, "battery_plugged": None}))
        monitor = SystemSignalMonitor(bus, probe=lambda: next(values)); monitor.check_once(); monitor.check_once()
        self.assertEqual(len(pressure), 0); self.assertEqual(len(critical), 1)

    def test_battery_plug_unplug_rearms_and_confidence_is_not_upgraded(self):
        bus = EventBus(); low = []; bus.subscribe("system.battery_low", low.append)
        values = iter((10, 10, 10)); plugged = iter((False, True, False))
        monitor = SystemSignalMonitor(bus, probe=lambda: {"memory_percent": 1, "disk_percent": 1, "battery_percent": next(values), "battery_plugged": next(plugged)})
        for _ in range(3): monitor.check_once()
        self.assertEqual(len(low), 2)
        for _engine, bus, voice, notes in self.make(mode="companion"):
            bus.publish("system.memory_pressure", {"value": 91}, source="system_signals", confidence=.2)
            self.assertFalse(voice.calls); self.assertFalse(notes.snapshot())
            bus.publish("device.disconnected", {}, source="hardware", confidence=.2)
            self.assertFalse(notes.snapshot())

    def test_context_changes_decision_metadata_and_proposal_is_pending(self):
        candidate = InterventionCandidate("x", "test", "coding", "errore", .95, .95, relevance=.7, fingerprint="x")
        plain = CompanionEngine._contextualize_candidate(candidate, {})
        coding = CompanionEngine._contextualize_candidate(candidate, {"active_window": {"title": "VS Code"}, "current_task": [{"id": "m"}]})
        self.assertGreater(coding.relevance, plain.relevance)
        for engine, bus, _voice, _ in self.make(mode="companion"):
            bus.publish("system.memory_pressure", {"value": 91}, source="system_signals")
            pending = engine.consume_pending_context()
            self.assertEqual(pending["proposal"]["intent"], "inspect_memory_usage")
            self.assertNotIn("command", pending["proposal"])

    def test_preferences_boolean_malformed_and_lifecycle_restart(self):
        for engine, _, _, _ in self.make():
            engine.set_enabled("false"); self.assertFalse(engine.snapshot()["enabled"])
            with self.assertRaises(ValueError): engine.set_enabled("maybe")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text('{"config": {}, "muted_categories": "system"}', encoding="utf-8")
            engine = CompanionEngine(EventBus(), StateManager(EventBus()), Voice(), persistence_path=path)
            self.assertEqual(engine.snapshot()["muted_categories"], [])
            path.write_text('{"config": {}, "muted_categories": [' + ','.join(f'"cat{i}"' for i in range(1000)) + ']}', encoding="utf-8")
            bounded = CompanionEngine(EventBus(), StateManager(EventBus()), Voice(), persistence_path=path)
            self.assertEqual(len(bounded.snapshot()["muted_categories"]), 32)
            bounded._persist()
            self.assertEqual(len(__import__("json").loads(path.read_text(encoding="utf-8"))["muted_categories"]), 32)
        bus = EventBus(); monitor = SystemSignalMonitor(bus, interval=60, probe=lambda: {"memory_percent": 1, "disk_percent": 1, "battery_percent": None, "battery_plugged": None})
        monitor.start(); monitor.start(); self.assertTrue(monitor.healthy()); monitor.restart(); self.assertTrue(monitor.healthy()); monitor.stop(); self.assertFalse(monitor.healthy())

    def test_cheap_gates_bound_context_and_recent_fingerprints(self):
        calls = []
        for _engine, bus, voice, _notes in self.make(context_provider=lambda: calls.append({}) or {}):
            for _ in range(1000): bus.publish("device.disconnected", {}, source="hardware")
            self.assertLessEqual(len(calls), 1); self.assertLessEqual(len(voice.calls), 1)
        calls = []
        for _engine, bus, _voice, _notes in self.make(mode="do_not_disturb", context_provider=lambda: calls.append({}) or {}):
            bus.publish("system.battery_critical", {"value": 4}, source="system_signals")
            self.assertEqual(len(calls), 0)
        calls = []
        for engine, bus, _voice, notes in self.make(context_provider=lambda: calls.append({}) or {}):
            bus.publish("system.memory_pressure", {"value": 91}, source="system_signals", confidence=.2)
            self.assertEqual(len(calls), 0); self.assertFalse(notes.snapshot())
            for index in range(1000):
                engine.evaluate(InterventionCandidate("unique", "test", "coding", "x", .95, .95, fingerprint=f"{index}"))
            self.assertLessEqual(len(engine._recent), 256)

    def test_critical_to_warning_updates_without_renotifying(self):
        bus = EventBus(); seen = []; bus.subscribe("system.memory_critical", seen.append); warnings = []; bus.subscribe("system.memory_pressure", warnings.append)
        values = iter((99, 96, 94, 98)); monitor = SystemSignalMonitor(bus, probe=lambda: {"memory_percent": next(values), "disk_percent": 1, "battery_percent": None, "battery_plugged": None})
        for _ in range(4): monitor.check_once()
        self.assertEqual(len(seen), 1); self.assertEqual(len(warnings), 0)

    def test_lifecycle_restart_replaces_thread(self):
        bus = EventBus(); monitor = SystemSignalMonitor(bus, interval=60, probe=lambda: {"memory_percent": 1, "disk_percent": 1, "battery_percent": None, "battery_plugged": None})
        monitor.start(); old_thread = monitor._thread; monitor.start(); self.assertIs(monitor._thread, old_thread)
        monitor.restart(); new_thread = monitor._thread
        self.assertIsNot(new_thread, old_thread); self.assertFalse(old_thread.is_alive()); self.assertTrue(new_thread.is_alive())
        monitor.stop(); self.assertFalse(new_thread.is_alive()); self.assertFalse(monitor.healthy())

    def test_battery_critical_is_high_priority_when_allowed(self):
        for _engine, bus, voice, _ in self.make():
            bus.publish("system.battery_critical", {"value": 4}, source="system_signals")
            self.assertEqual(len(voice.calls), 1)

    def test_dnd_also_silences_critical(self):
        for _engine, bus, voice, notes in self.make(mode="do_not_disturb"):
            bus.publish("system.battery_critical", {"value": 4}, source="system_signals")
            self.assertFalse(voice.calls)
            self.assertFalse(notes.snapshot())

    def test_dnd_and_focus_never_speak_noncritical(self):
        for mode in ("do_not_disturb", "focus"):
            for _engine, bus, voice, notes in self.make(mode=mode):
                bus.publish("system.memory_pressure", {"value": 91}, source="system_signals")
                self.assertFalse(voice.calls)
                if mode == "do_not_disturb": self.assertFalse(notes.snapshot())

    def test_hud_only_is_delivered_and_feedback_does_not_recurse(self):
        for engine, bus, voice, notes in self.make(mode="companion"):
            bus.publish("device.disconnected", {}, source="hardware")
            self.assertTrue(notes.snapshot())
            self.assertFalse(voice.calls)
            self.assertEqual(engine.snapshot()["metrics"]["hud_interventions"], 1)

    def test_duplicate_storm_is_bounded_and_no_tools_are_available(self):
        for engine, bus, voice, _ in self.make(mode="companion"):
            for _ in range(1000): bus.publish("system.disk_pressure", {"value": 91}, source="system_signals")
            self.assertLessEqual(len(voice.calls), 1)
            self.assertEqual(engine.snapshot()["metrics"]["candidates"], 1000)
            self.assertNotIn("execute", dir(engine))

    def test_preference_persist_and_stop_have_one_lock_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            bus = EventBus(); engine = CompanionEngine(bus, StateManager(bus), Voice(), persistence_path=path)
            engine.start()
            persist_entered = threading.Event(); release_persist = threading.Event()

            class GateLock:
                def __init__(self): self.lock = threading.Lock()
                def __enter__(self):
                    self.lock.acquire(); persist_entered.set(); release_persist.wait(2); return self
                def __exit__(self, *_): self.lock.release()

            engine._persist_lock = GateLock()
            mutation_done = threading.Event(); stop_done = threading.Event(); errors = []

            def mutate():
                try: engine.set_enabled(False)
                except Exception as exc: errors.append(exc)
                finally: mutation_done.set()

            def stop():
                try: engine.stop()
                except Exception as exc: errors.append(exc)
                finally: stop_done.set()

            first = threading.Thread(target=mutate); first.start(); self.assertTrue(persist_entered.wait(1))
            second = threading.Thread(target=stop); second.start()
            for _ in range(20):
                if not engine.snapshot()["running"]: break
                threading.Event().wait(.01)
            self.assertFalse(engine.snapshot()["running"])
            release_persist.set()
            self.assertTrue(mutation_done.wait(2)); first.join(1); second.join(1)
            self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive()); self.assertFalse(errors)
            self.assertFalse(engine.snapshot()["running"])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(persisted["config"]["enabled"], (True, False))


if __name__ == "__main__": unittest.main()
