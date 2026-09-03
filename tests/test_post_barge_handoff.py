import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import voice


class PostBargeHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path("voice.py").read_text(encoding="utf-8"))
        cls.functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    @staticmethod
    def calls(function, name):
        return [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ]

    def test_barge_in_only_returns_wake_handoff_and_does_not_transcribe(self):
        barge = self.functions["ascolta_barge_in"]
        self.assertEqual(len(self.calls(barge, "trascrivi")), 0)
        self.assertIn("jarvis", [
            node.value for node in ast.walk(barge)
            if isinstance(node, ast.Constant) and node.value == "jarvis"
        ])

    def test_normal_stt_has_a_fresh_stream_and_transcriber(self):
        stt = self.functions["ascolta"]
        self.assertTrue(self.calls(stt, "input_stream"))
        self.assertTrue(self.calls(stt, "StreamingTranscriber"))
        self.assertTrue(self.calls(stt, "_transcribe_with_fallback"))

    def test_transition_diagnostics_are_present(self):
        source = Path("voice.py").read_text(encoding="utf-8")
        for label in (
            "wake word barge-in rilevata", "mixer stop", "stream barge-in chiuso",
            "nuovo stream STT aperto", "primo frame STT ricevuto",
            "voce rilevata da VAD", "testo Vosk pronto", "testo OpenAI pronto",
        ):
            self.assertIn(label, source)

    def test_diagnostic_failure_does_not_propagate_when_pair_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(voice, "_stt_diag_dir", target):
                voice._write_stt_diagnostic(
                    "post_barge",
                    [b"\0" * 960],
                    [b"\0" * 960],
                    [0.0],
                    1.0,
                    2.0,
                    1.1,
                    1.2,
                    {"frame": 1},
                    "test",
                    "test",
                    1,
                )
            self.assertTrue((target / "post_barge_raw.wav").exists())
            self.assertTrue((target / "post_barge_stt.wav").exists())


if __name__ == "__main__":
    unittest.main()
