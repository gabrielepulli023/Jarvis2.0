import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation

import presentation_tools
from jarvis_identity.service import IdentityService
from jarvis_identity.store import BiometricStore


class PresentationCapabilityTests(unittest.TestCase):
    def test_creates_real_powerpoint_in_desktop_target(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation_tools, "_desktop_directory", return_value=Path(folder).resolve()):
            result = presentation_tools.crea_presentazione(
                "Intelligenza artificiale",
                [{"titolo": "Origini", "contenuto": ["Primi sistemi", "Machine learning"]},
                 {"titolo": "Futuro", "contenuto": ["Scenari", "Rischi"]}],
                "Ricerca AI.pptx",
            )
            self.assertTrue(result["successo"])
            path = Path(result["dati"]["percorso"])
            self.assertTrue(path.is_file())
            self.assertEqual(len(Presentation(path).slides), 3)

    def test_empty_presentation_fails_without_writing(self):
        self.assertFalse(presentation_tools.crea_presentazione("Vuota", [], "vuota.pptx")["successo"])

    def test_recognition_without_enrollment_does_not_open_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            service = IdentityService(BiometricStore(Path(folder)))
            with patch.object(service, "capture_faces") as capture:
                with self.assertRaisesRegex(RuntimeError, "nessun profilo facciale"):
                    service.recognize_face()
                capture.assert_not_called()
            with patch.object(service, "record_audio") as record:
                with self.assertRaisesRegex(RuntimeError, "nessun profilo vocale"):
                    service.recognize_voice()
                record.assert_not_called()

    def test_router_exposes_presentation_tool(self):
        import brain
        schemas = {item.get("name") for item in brain.TOOLS}
        self.assertIn("crea_presentazione", schemas)
        self.assertIs(brain.FUNZIONI["crea_presentazione"], presentation_tools.crea_presentazione)


if __name__ == "__main__":
    unittest.main()
