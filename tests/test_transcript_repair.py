import unittest
from unittest.mock import Mock, patch

from transcript_repair import repair_transcript


class TranscriptRepairTests(unittest.TestCase):
    def test_operational_entities_are_resolved_by_context(self):
        cases = {
            "apri krom": "apri Chrome",
            "apri crom": "apri Chrome",
            "avvia google crom": "avvia Google Chrome",
            "chiudi krom": "chiudi Chrome",
            "apri spotifai": "apri Spotify",
            "apri discor": "apri Discord",
            "vai su iutub": "vai su YouTube",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = repair_transcript(raw)
                self.assertEqual(result.normalized_transcript, expected)
                self.assertEqual(result.confidence_band, "high")
                self.assertEqual(result.raw_transcript, raw)

    def test_exact_name_is_unchanged(self):
        result = repair_transcript("apri Chrome")
        self.assertEqual(result.normalized_transcript, "apri Chrome")
        self.assertEqual(result.confidence, 1.0)

    def test_ambiguity_requests_clarification(self):
        result = repair_transcript("apri krom", candidates=["Chrome", "Krome"])
        self.assertTrue(result.clarification)
        self.assertEqual(result.normalized_transcript, result.raw_transcript)

    def test_unknown_and_non_command_data_are_preserved(self):
        for raw in ("apri programma sconosciuto", "vai su https://youtube.com", "scrivi codice Python"):
            with self.subTest(raw=raw):
                result = repair_transcript(raw)
                self.assertEqual(result.normalized_transcript, raw)

    def test_openai_transcription_uses_configured_italian_and_context(self):
        response = Mock(text="apri krom")
        client = Mock()
        client.audio.transcriptions.create.return_value = response
        with patch("transcriber.client", client), patch("transcriber.get_setting", return_value="it"):
            from transcriber import trascrivi
            with patch("builtins.open", unittest.mock.mock_open(read_data=b"wav")):
                self.assertEqual(trascrivi("input.wav"), "apri krom")
        kwargs = client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(kwargs["language"], "it")
        self.assertIn("Chrome", kwargs["prompt"])


if __name__ == "__main__":
    unittest.main()
