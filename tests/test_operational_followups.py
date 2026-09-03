import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.operational_context import OperationalContext
from jarvis_core.operational_followup import execute
from jarvis_files import FileAgent, FileOperation


class OperationalFollowupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jarvis_followup_"))
        self.desktop = self.root / "Desktop"
        self.downloads = self.root / "Downloads"
        self.desktop.mkdir()
        self.downloads.mkdir()
        self.agent = FileAgent([self.desktop, self.downloads], self.root / "transactions")
        self.now = [1000.0]
        self.context = OperationalContext(clock=lambda: self.now[0])

    def _conversion(self, *, skill="documents.markitdown", source_name="Build-PC.pdf", content="# Build PC\n\nCPU"):
        source = self.downloads / source_name
        source.write_bytes(b"source")
        self.context.record(
            "expansion_call",
            {
                "successo": True,
                "skill": skill,
                "dati": {"path": str(source), "markdown": content, "truncated": False},
                "verification": {"status": "verified", "strength": 1.0},
            },
            {"skill": skill, "path": str(source)},
        )
        return source

    def _writer(self, path, content):
        target = Path(path)
        plan = self.agent.plan([FileOperation("write", target=str(target), content=content)])
        result = self.agent.execute(plan, confirmed=True)
        return {
            "successo": result.success,
            "messaggio": "File scritto e verificato." if result.success else "; ".join(result.errors),
            "dati": {"path": str(target), "verified": result.success},
            "verification": {"status": "verified" if result.success else "failed"},
        }

    @staticmethod
    def _opener(path, application=None):
        return {
            "successo": True,
            "messaggio": "Aperto.",
            "dati": {"path": str(path), "application": application},
            "verification": {"status": "verified"},
        }

    def test_markitdown_save_to_desktop_creates_real_file(self):
        source = self._conversion()
        stored = self.context.current()
        self.assertEqual(stored["tool"], "expansion_call")
        self.assertEqual(stored["skill"], "documents.markitdown")
        self.assertEqual(stored["source_path"], str(source))
        self.assertEqual(stored["markdown"], "# Build PC\n\nCPU")
        self.assertEqual(stored["filename"], "Build-PC.md")
        self.assertEqual(stored["status"], "succeeded")
        self.assertIn("timestamp", stored)
        with patch("jarvis_core.operational_followup.Path.home", return_value=self.root):
            handled, message, result = execute(
                "salvalo sul desktop",
                self.context.current(),
                writer=self._writer,
                opener=self._opener,
            )
        target = self.desktop / "Build-PC.md"
        self.assertTrue(handled)
        self.assertTrue(result["successo"])
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), "# Build PC\n\nCPU")
        self.assertIn("Build-PC.md", message)

    def test_markitdown_save_to_downloads_creates_real_file(self):
        self._conversion()
        with patch("jarvis_core.operational_followup.Path.home", return_value=self.root):
            handled, message, result = execute(
                "mettilo nei Download",
                self.context.current(),
                writer=self._writer,
                opener=self._opener,
            )
        target = self.downloads / "Build-PC.md"
        self.assertTrue(handled)
        self.assertTrue(result["successo"])
        self.assertEqual(target.read_text(encoding="utf-8"), "# Build PC\n\nCPU")
        self.assertIn("Downloads", message)

    def test_docling_result_keeps_working_with_same_generic_followup(self):
        self._conversion(skill="documents.docling", source_name="manual.pdf", content="## Manual\n\nPasso 1")
        with patch("jarvis_core.operational_followup.Path.home", return_value=self.root):
            _, _, result = execute(
                "esportalo sul desktop",
                self.context.current(),
                writer=self._writer,
                opener=self._opener,
            )
        self.assertTrue(result["successo"])
        self.assertEqual((self.desktop / "manual.md").read_text(encoding="utf-8"), "## Manual\n\nPasso 1")

    def test_failed_operation_cannot_be_confirmed_as_done(self):
        self.context.record(
            "expansion_call",
            {"successo": False, "messaggio": "MarkItDown non disponibile."},
            {"skill": "documents.markitdown"},
        )
        handled, message, result = execute(
            "salvalo sul desktop",
            self.context.current(),
            writer=self._writer,
            opener=self._opener,
        )
        self.assertTrue(handled)
        self.assertFalse(result["successo"])
        self.assertNotRegex(message.casefold(), r"\b(?:fatto|salvato|creato)\b")
        self.assertFalse(list(self.desktop.iterdir()))

    def test_success_without_verification_is_not_reusable(self):
        source = self.downloads / "unchecked.pdf"
        source.write_bytes(b"source")
        self.context.record(
            "expansion_call",
            {"successo": True, "dati": {"path": str(source), "markdown": "# unchecked"}},
            {"skill": "documents.markitdown"},
        )
        stored = self.context.current()
        self.assertEqual(stored["status"], "unverified")
        handled, message, result = execute(
            "salvalo sul desktop",
            stored,
            writer=self._writer,
            opener=self._opener,
        )
        self.assertTrue(handled)
        self.assertFalse(result["successo"])
        self.assertNotIn("unchecked.md", message)

    def test_followup_without_context_asks_instead_of_inventing_content(self):
        handled, message, result = execute(
            "salvalo sul desktop",
            None,
            writer=self._writer,
            opener=self._opener,
        )
        self.assertTrue(handled)
        self.assertFalse(result["successo"])
        self.assertIn("Indica cosa", message)
        self.assertFalse(list(self.desktop.iterdir()))

    def test_expired_context_is_not_reused(self):
        self._conversion()
        self.now[0] += 301
        self.assertIsNone(self.context.current())
        handled, message, result = execute(
            "salvalo sul desktop",
            self.context.current(),
            writer=self._writer,
            opener=self._opener,
        )
        self.assertTrue(handled)
        self.assertFalse(result["successo"])
        self.assertNotIn("Build-PC.md", message)
        self.assertFalse(list(self.desktop.iterdir()))

    def test_file_agent_root_is_still_enforced(self):
        from jarvis_core.errors import PermissionError

        outside = self.root.parent / (self.root.name + "_outside.md")
        try:
            with self.assertRaises(PermissionError):
                plan = self.agent.plan([FileOperation("write", target=str(outside), content="nope")])
                self.agent.execute(plan, confirmed=True)
            self.assertFalse(outside.exists())
        finally:
            outside.unlink(missing_ok=True)

    def test_runtime_writer_checks_permission_before_file_agent(self):
        from jarvis_core.runtime import RUNTIME

        target = self.desktop / "denied.md"
        with patch("jarvis_core.runtime.permission_decision", return_value="deny"), patch.object(RUNTIME.file_agent, "plan") as plan:
            result = RUNTIME.write_text_file(str(target), "nope")
        self.assertFalse(result["successo"])
        self.assertNotIn("dati", result)
        plan.assert_not_called()
        self.assertFalse(target.exists())

    def test_router_classifies_pronominal_followup_as_operational(self):
        import main

        self._conversion()
        self.assertTrue(main.deve_usare_router_operativo("salvalo sul desktop"))
        self.assertTrue(main.deve_usare_router_operativo("ok", self.context.current()))
        self.assertFalse(main.deve_usare_router_operativo("procedi", "vecchio risultato testuale"))

    def test_expansion_call_payload_is_recorded_by_central_tool_executor(self):
        import brain

        source = self.downloads / "Build-PC.pdf"
        source.write_bytes(b"source")
        brain.CORE_RUNTIME.context.operational.clear()
        expansion_result = SimpleNamespace(
            success=True,
            message="Conversione completata.",
            data={"path": str(source), "markdown": "# extracted", "truncated": False},
            skill="documents.markitdown",
        )
        try:
            with patch.object(brain.CORE_RUNTIME.skills, "execute", return_value=expansion_result):
                result = brain.esegui_tool(
                    "expansion_call",
                    {"skill": "documents.markitdown", "arguments_json": "{}"},
                )
            self.assertTrue(result["successo"])
            stored = brain.CORE_RUNTIME.context.operational_context()
            self.assertEqual(stored["skill"], "documents.markitdown")
            self.assertEqual(stored["markdown"], "# extracted")
            self.assertEqual(stored["filename"], "Build-PC.md")
            self.assertEqual(stored["status"], "succeeded")
        finally:
            brain.CORE_RUNTIME.context.operational.clear()

    def test_conversational_fallback_cannot_claim_an_unexecuted_save(self):
        import main

        worker = main.JarvisWorker()
        with patch.object(main, "chiedi_jarvis") as chat, patch.object(worker, "parla_controllato") as speak:
            worker.risposta_ai("salvalo sul desktop")
        chat.assert_not_called()
        self.assertNotIn("salvato", str(speak.call_args).casefold())


if __name__ == "__main__":
    unittest.main()
