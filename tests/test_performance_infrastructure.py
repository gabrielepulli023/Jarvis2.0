import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import performance_metrics
from jarvis_core.tracing import PerformanceTrace, TraceStore


class PerformanceInfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.gettempdir()) / "jarvis_metrics_test.json"
        self.path.unlink(missing_ok=True)
        performance_metrics._DATA = None; performance_metrics._DIRTY = False
        performance_metrics._LAST_FLUSH = time.monotonic()

    def tearDown(self):
        self.path.unlink(missing_ok=True); performance_metrics._DATA = None

    def test_hot_path_is_buffered_and_flush_has_percentiles(self):
        with patch.object(performance_metrics, "STORE", self.path):
            for value in range(1, 101): performance_metrics.record_tool("router", True, value)
            self.assertFalse(self.path.exists())
            self.assertTrue(performance_metrics.flush())
            row = json.loads(self.path.read_text(encoding="utf-8"))["router"]
        self.assertEqual(row["calls"], 100); self.assertEqual(row["p50_ms"], 50)
        self.assertEqual(row["p95_ms"], 95); self.assertEqual(row["p99_ms"], 99)

    def test_trace_is_correlated_monotonic_and_bounded(self):
        ticks = iter((1_000_000, 2_000_000, 4_000_000))
        trace = PerformanceTrace("command-1", clock=lambda: next(ticks))
        trace.mark("intent"); trace.mark("dispatch")
        snapshot = trace.snapshot(); self.assertEqual(snapshot["command_id"], "command-1")
        self.assertEqual([row["elapsed_ms"] for row in snapshot["timeline"]], [1.0, 3.0])
        store = TraceStore(limit=1); store.add(trace); store.add(trace)
        self.assertEqual(len(store.snapshot()), 1)


if __name__ == "__main__": unittest.main()
