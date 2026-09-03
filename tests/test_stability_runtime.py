import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import settings_store
from jarvis_core.crash_report import write_crash


class StabilityRuntimeTests(unittest.TestCase):
    def test_settings_normalize_corrupt_scalar_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"voice_rate": "invalid", "performance_mode": "off", "market_refresh_seconds": "15"}), encoding="utf-8")
            with patch.object(settings_store, "SETTINGS_FILE", path):
                settings_store._CACHE = None; settings_store._CACHE_SIGNATURE = None
                self.assertEqual(settings_store.get_setting("voice_rate"), -4)
                self.assertFalse(settings_store.get_setting("performance_mode"))
                self.assertEqual(settings_store.get_setting("market_refresh_seconds"), 15)

    def test_new_runtime_settings_are_type_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"startup_stage_timeout_seconds": "bad", "local_streaming_stt": "off"}), encoding="utf-8")
            with patch.object(settings_store, "SETTINGS_FILE", path):
                settings_store._CACHE = None; settings_store._CACHE_SIGNATURE = None
                self.assertEqual(settings_store.get_setting("startup_stage_timeout_seconds"), 20.0)
                self.assertFalse(settings_store.get_setting("local_streaming_stt"))

    def test_set_setting_normalizes_scalar_types_before_persisting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(settings_store, "SETTINGS_FILE", path):
                settings_store._CACHE = None; settings_store._CACHE_SIGNATURE = None
                self.assertEqual(settings_store.set_setting("voice_rate", "invalid"), -4)
                self.assertEqual(settings_store.get_setting("voice_rate"), -4)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["voice_rate"], -4)
                updated = settings_store.update_settings({"market_refresh_seconds": "bad"})
                self.assertEqual(updated["market_refresh_seconds"], 60)

    def test_settings_cache_invalidates_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"performance_mode": true}', encoding="utf-8")
            with patch.object(settings_store, "SETTINGS_FILE", path):
                settings_store._CACHE = None; settings_store._CACHE_SIGNATURE = None
                self.assertTrue(settings_store.get_setting("performance_mode"))
                time.sleep(.002)
                path.write_text('{"performance_mode": false}', encoding="utf-8")
                self.assertFalse(settings_store.get_setting("performance_mode"))
                settings_store.set_setting("performance_mode", True)
                self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["performance_mode"])
                self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_crash_report_contains_thread_and_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash.jsonl"
            try:
                raise RuntimeError("deliberate crash")
            except RuntimeError as exc:
                self.assertTrue(write_crash(type(exc), exc, exc.__traceback__, thread_name="worker-x", path=path))
            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["thread"], "worker-x"); self.assertEqual(row["exception_type"], "RuntimeError")
            self.assertIn("deliberate crash", row["traceback"])


if __name__ == "__main__": unittest.main()
