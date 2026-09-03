import threading
import time
import unittest

from jarvis_core.events import EventBus
from jarvis_core.recovery import RecoveryEngine, RecoveryPolicy, RecoveryStrategy


class RecoveryEngineTests(unittest.TestCase):
    def test_fallback_strategy_is_verified(self):
        state = {"open": False}; events = []; bus = EventBus(); bus.subscribe("*", events.append)
        engine = RecoveryEngine(bus, RecoveryPolicy(max_retries=0, action_timeout=.2, global_timeout=1))
        strategies = [
            RecoveryStrategy("primary", lambda: {"success": False}, lambda after, result: False),
            RecoveryStrategy("fallback", lambda: (state.update(open=True) or {"success": True}), lambda after, result: after["open"]),
        ]
        result = engine.run("open_app", strategies, lambda: dict(state)); engine.shutdown()
        self.assertTrue(result.success); self.assertEqual(result.strategy, "fallback"); self.assertEqual(len(result.attempts), 2)
        self.assertEqual(events[-1].topic, "recovery.completed")

    def test_retries_are_bounded(self):
        calls = [] ; engine = RecoveryEngine(EventBus(), RecoveryPolicy(max_retries=2, action_timeout=.1, global_timeout=1))
        result = engine.run("x", [RecoveryStrategy("x", lambda: (calls.append(1) or {"success": False}), lambda *_: False)], lambda: {})
        engine.shutdown(); self.assertFalse(result.success); self.assertEqual(result.final_status, "exhausted"); self.assertEqual(len(calls), 3)

    def test_pre_cancelled_run_executes_nothing(self):
        cancel = threading.Event(); cancel.set(); calls = []
        engine = RecoveryEngine(EventBus(), RecoveryPolicy(max_retries=0, action_timeout=.1, global_timeout=1))
        result = engine.run("x", [RecoveryStrategy("x", lambda: calls.append(1), lambda *_: True)], lambda: {}, cancellation=cancel)
        engine.shutdown(); self.assertEqual(result.final_status, "cancelled"); self.assertEqual(calls, [])

    def test_timeout_moves_to_failure_without_infinite_loop(self):
        engine = RecoveryEngine(EventBus(), RecoveryPolicy(max_retries=0, action_timeout=.02, global_timeout=.1))
        result = engine.run("slow", [RecoveryStrategy("slow", lambda: time.sleep(.1) or {"success": True}, lambda *_: True)], lambda: {})
        engine.shutdown(); self.assertFalse(result.success); self.assertEqual(result.attempts[0].error, "action_timeout")


if __name__ == "__main__": unittest.main()
