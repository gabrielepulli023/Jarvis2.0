import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from jarvis_files import FileIndexer


class FileIndexerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.indexer = FileIndexer(self.root / "index.db", [self.root])
    def tearDown(self): self.temp.cleanup()

    def test_indexes_name_metadata_and_safe_text_content(self):
        target = self.root / "appunti_moto.txt"; target.write_text("Discussione sulla motocicletta e sul casco", encoding="utf-8")
        stats = self.indexer.scan(); results = self.indexer.search("moto casco", extension="txt")
        self.assertGreaterEqual(stats.indexed, 1); self.assertEqual(results[0]["path"], str(target.resolve()))

    def test_skips_credentials_and_redacts_inline_secrets(self):
        (self.root / ".env").write_text("API_KEY=forbidden", encoding="utf-8")
        source = self.root / "safe.py"; source.write_text("API_KEY='hidden'\nprint('visible marker')", encoding="utf-8")
        stats = self.indexer.scan()
        self.assertGreaterEqual(stats.skipped_sensitive, 1); self.assertEqual(self.indexer.search("forbidden"), [])
        self.assertEqual(self.indexer.search("hidden"), []); self.assertEqual(self.indexer.search("visible marker")[0]["path"], str(source.resolve()))

    def test_time_filter_and_incremental_update(self):
        target = self.root / "recent.md"; target.write_text("alpha", encoding="utf-8")
        first = self.indexer.scan(); second = self.indexer.scan()
        self.assertGreaterEqual(first.indexed, 1); self.assertEqual(second.indexed, 0)
        future = datetime.now() + timedelta(days=1)
        self.assertEqual(self.indexer.search("alpha", modified_after=future), [])


if __name__ == "__main__": unittest.main()
