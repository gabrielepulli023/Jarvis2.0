import sys
import tempfile
import unittest
from pathlib import Path
from jarvis_core.events import EventBus
from jarvis_core.processes import ProcessManager
from jarvis_terminal import CommandValidator, TerminalAgent, WorkingDirectoryGuard


class TerminalAgentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.processes = ProcessManager(EventBus())
        self.agent = TerminalAgent(self.root, self.processes)

    def tearDown(self):
        self.processes.shutdown()

    def test_python_version_runs_and_records_complete_evidence(self):
        result = self.agent.execute([sys.executable, "--version"])
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["exit_code"], 0)
        self.assertIn("duration_ms", result["data"])

    def test_inline_code_and_unknown_executable_are_denied(self):
        with self.assertRaises(PermissionError):
            self.agent.execute([sys.executable, "-c", "open('x','w')"])
        with self.assertRaises(PermissionError):
            self.agent.execute(["totally-unknown.exe", "x"])

    def test_cwd_and_script_must_stay_in_workspace(self):
        with self.assertRaises(PermissionError):
            WorkingDirectoryGuard(self.root).validate(self.root.parent)
        with self.assertRaises(PermissionError):
            CommandValidator(self.root).validate([sys.executable, str(self.root.parent / "x.py")])

    def test_powershell_inline_and_dangerous_git_are_denied(self):
        validator = CommandValidator(self.root)
        with self.assertRaises(PermissionError):
            validator.validate(["powershell.exe", "-Command", "Remove-Item x"])
        with self.assertRaises(PermissionError):
            validator.validate(["git", "clean", "-fdx"])

    def test_python_venv_module_is_allowed_for_project_bootstrap(self):
        command = CommandValidator(self.root).validate([sys.executable, "-m", "venv", ".venv"])
        self.assertEqual(command[1:], ["-m", "venv", ".venv"])


if __name__ == "__main__":
    unittest.main()
