import os
import unittest
from unittest.mock import patch

import ai


class DiagnosticModeTests(unittest.TestCase):
    def test_direct_openai_mode_bypasses_router_and_memory(self):
        fake_response = type("Resp", (), {"output_text": "TEST OK"})()

        with patch.dict(os.environ, {"JARVIS_DIAGNOSTIC_MODE": "1"}, clear=False):
            with patch.object(ai, "openai_client") as openai_client_mock:
                openai_client_mock.return_value.responses.create.return_value = fake_response
                result = list(ai.chiedi_jarvis("Ciao. Rispondi solamente con: TEST OK"))

        self.assertEqual(result, ["TEST OK"])
        openai_client_mock.return_value.responses.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
