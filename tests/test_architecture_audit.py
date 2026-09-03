import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_system.clipboard import ClipboardManager

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"venv", ".runtime-env", ".build-env-current", ".python", "build", "dist", "backups"}


def project_python_files():
    yield from ROOT.glob("*.py")
    for directory in [
        path for path in ROOT.iterdir() if path.is_dir() and (path.name.startswith("jarvis_") or path.name == "tests")
    ]:
        yield from directory.rglob("*.py")


class ArchitectureAuditTests(unittest.TestCase):
    def test_no_bare_except_in_project_code(self):
        violations = []
        for path in project_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations)

    def test_openai_sdk_is_constructed_only_by_gateway(self):
        violations = []
        for path in project_python_files():
            if path.name == "llm_gateway.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id
                    in {
                        "OpenAI",
                        "AsyncOpenAI",
                    }
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations)

    @patch("jarvis_system.clipboard.ImageGrab.grabclipboard", return_value=None)
    @patch("jarvis_system.clipboard.pyperclip.paste")
    def test_clipboard_summary_is_explicit_bounded_and_non_persistent(self, paste, _grab):
        paste.return_value = "Prima frase. Seconda frase! Terza frase?"
        result = ClipboardManager().summarize(max_sentences=2)
        self.assertTrue(result["success"])
        self.assertEqual("Prima frase. Seconda frase!…", result["message"])
        self.assertFalse(result["data"]["persistent"])


if __name__ == "__main__":
    unittest.main()
