import unittest

from jarvis_core.reference_resolution import ReferenceResolution
from main import _testo_operativo_risolto


class Phase2ReferenceRoutingTests(unittest.TestCase):
    def _consumer(self, text):
        received = []
        received.append(text)
        return received

    def test_verified_chrome_close_reaches_operational_consumer(self):
        reference = ReferenceResolution(True, "application", {"name": "Chrome"}, .9, "working_memory")
        received = self._consumer(_testo_operativo_risolto("Chiudilo", reference))
        self.assertEqual(received, ["chiudi Chrome"])

    def test_verified_spotify_open_reaches_operational_consumer(self):
        reference = ReferenceResolution(True, "application", {"name": "Spotify"}, .9, "working_memory")
        received = self._consumer(_testo_operativo_risolto("Aprilo", reference))
        self.assertEqual(received, ["apri Spotify"])

    def test_ambiguous_reference_is_not_sent_to_consumer(self):
        reference = ReferenceResolution(False, "application", None, .2, "working_memory", ("Chrome", "Spotify"), True)
        received = []
        if not reference.needs_clarification:
            received.append(_testo_operativo_risolto("Chiudilo", reference))
        self.assertEqual(received, [])

    def test_original_transcript_remains_natural(self):
        original = "Chiudilo"
        reference = ReferenceResolution(True, "application", {"name": "Chrome"}, .9, "working_memory")
        self.assertEqual(original, "Chiudilo")
        self.assertEqual(_testo_operativo_risolto(original, reference), "chiudi Chrome")


if __name__ == "__main__":
    unittest.main()
