import unittest
from unittest.mock import patch

from proactive import ProactiveMonitorWorker


class ProactiveMonitorTests(unittest.TestCase):
    def test_monitor_reports_failures_with_cooldown(self):
        worker = ProactiveMonitorWorker()
        with patch("proactive.LOGGER.warning") as warning:
            worker._report_error(RuntimeError("one"))
            worker._report_error(RuntimeError("two"))
        warning.assert_called_once_with("Monitor proattivo degradato: %s", "RuntimeError")


if __name__ == "__main__":
    unittest.main()
