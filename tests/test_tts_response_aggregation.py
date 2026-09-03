import ast
import unittest
from pathlib import Path


class TtsResponseAggregationTests(unittest.TestCase):
    def test_main_accumulates_streamed_phrases_before_speaking(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "risposta_ai"
        )
        calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "parla_controllato"
        ]
        self.assertEqual(len(calls), 2)  # normal response plus error fallback
        normal_call = next(
            node
            for node in calls
            if node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "testo_voce"
        )
        self.assertIsNotNone(normal_call)


if __name__ == "__main__":
    unittest.main()
