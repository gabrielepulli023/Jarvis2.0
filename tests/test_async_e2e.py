import time
import unittest

from async_engine import AsyncEngine
from result_cache import clear, get, put


class AsyncEndToEndTests(unittest.TestCase):
    def test_lanes_do_not_block_each_other(self):
        engine = AsyncEngine()
        _, vision = engine.submit("vision", time.sleep, 0.25, label="vision")
        _, io = engine.submit("io", lambda: "ready", label="io")
        self.assertEqual(io.result(timeout=0.15), "ready")
        vision.result(timeout=1)
        snapshot = engine.snapshot()
        self.assertTrue(any(row["lane"] == "vision" for row in snapshot["history"]))
        engine.shutdown()

    def test_cached_observation_does_not_mutate_source(self):
        clear()
        original = {"elements": ["A"]}
        put("ui", original, 1)
        cached = get("ui")
        cached["elements"].append("B")
        self.assertEqual(get("ui")["elements"], ["A"])


if __name__ == "__main__":
    unittest.main()
