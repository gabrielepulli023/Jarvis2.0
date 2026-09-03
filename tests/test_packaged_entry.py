import sys
import unittest
from unittest.mock import patch

import jarvis_entry


class PackagedEntryTests(unittest.TestCase):
    def test_option_is_bounded_to_the_next_argument(self):
        with patch.object(sys, "argv", ["JARVIS.exe", "--broker-tcp-port", "54321"]):
            self.assertEqual(jarvis_entry._option("--broker-tcp-port"), "54321")
            self.assertIsNone(jarvis_entry._option("--missing"))


if __name__ == "__main__":
    unittest.main()
