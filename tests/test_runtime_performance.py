import unittest
from unittest.mock import patch
from jarvis_system import RuntimePerformanceMonitor


class RuntimePerformanceTests(unittest.TestCase):
    def test_pressure_and_memory_optimization_are_scoped(self):
        monitor = RuntimePerformanceMonitor()
        pressure = monitor.system_pressure(3)
        optimized = monitor.optimize_own_memory()
        self.assertTrue(pressure["success"])
        self.assertLessEqual(len(pressure["data"]["top_memory_processes"]), 3)
        self.assertTrue(optimized["success"])
        self.assertEqual(optimized["data"]["scope"], "jarvis_process_only")

    def test_snapshot_contains_process_queue_and_gpu_categories(self):
        monitor = RuntimePerformanceMonitor()
        snapshot = monitor.snapshot()
        self.assertTrue({"cpu_percent", "rss_bytes", "threads", "queues", "gpu"} <= snapshot.keys())
        self.assertGreater(snapshot["rss_bytes"], 0)

    def test_gpu_probe_is_fixed_bounded_and_cached(self):
        monitor = RuntimePerformanceMonitor()
        completed = type("Result", (), {"returncode": 0, "stdout": "GPU, 10, 100, 1000, 50\n", "stderr": ""})()
        with (
            patch("jarvis_system.performance.shutil.which", return_value="nvidia-smi"),
            patch("jarvis_system.performance.subprocess.run", return_value=completed) as run,
        ):
            self.assertTrue(monitor.snapshot()["gpu"]["available"])
            monitor.snapshot()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["timeout"], 3)
            self.assertFalse(run.call_args.kwargs["shell"])


if __name__ == "__main__":
    unittest.main()
