import json
import tempfile
import unittest
from pathlib import Path

from jarvis_hud import HUDSnapshotProvider


class _Value:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


class _MissionStore:
    def recent(self, limit=20):
        return [
            {"id": "1", "objective": "Repair audio", "status": "running"},
            {"id": "2", "objective": "Failed task", "status": "failed"},
        ][:limit]


class _Skills:
    def metrics(self):
        return [{"skill": "files.read", "uses": 2, "successes": 2}]


class HUDProviderTests(unittest.TestCase):
    def test_snapshot_aggregates_runtime_sources_and_alerts(self):
        runtime = type("Runtime", (), {})()
        runtime.mission_store = _MissionStore()
        runtime.health = _Value({"audio": {"status": "DEGRADED", "detail": "device busy"}})
        runtime.skills = _Skills()
        runtime.voice = _Value({"state": "idle", "queue_size": 0})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metrics = root / "metrics.json"
            metrics.write_text(json.dumps({"tts": {"average_ms": 42}}), encoding="utf-8")
            log = root / "jarvis.jsonl"
            log.write_text('{"event":"core.started","severity":"INFO"}\n', encoding="utf-8")
            snapshot = HUDSnapshotProvider(runtime, metrics, log).snapshot()
        self.assertEqual(snapshot["missions"]["counts"], {"running": 1, "failed": 1})
        self.assertEqual(snapshot["performance"]["tts"]["average_ms"], 42)
        self.assertEqual(snapshot["logs"][0]["event"], "core.started")
        self.assertEqual(len(snapshot["notifications"]), 2)

    def test_invalid_or_missing_files_are_safe(self):
        runtime = type("Runtime", (), {})()
        runtime.mission_store = _MissionStore()
        runtime.health = _Value({})
        runtime.skills = _Skills()
        runtime.voice = _Value({})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metrics = root / "metrics.json"
            metrics.write_text("invalid", encoding="utf-8")
            snapshot = HUDSnapshotProvider(runtime, metrics, root / "missing.jsonl").snapshot()
        self.assertEqual(snapshot["performance"], {})
        self.assertEqual(snapshot["logs"], [])

    def test_log_stream_is_bounded_to_last_150_rows(self):
        runtime = type("Runtime", (), {})()
        runtime.mission_store = _MissionStore()
        runtime.health = _Value({})
        runtime.skills = _Skills()
        runtime.voice = _Value({})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log = root / "jarvis.jsonl"
            log.write_text("\n".join(json.dumps({"event": str(i)}) for i in range(200)), encoding="utf-8")
            rows = HUDSnapshotProvider(runtime, root / "missing", log).snapshot()["logs"]
        self.assertEqual(len(rows), 150)
        self.assertEqual(rows[0]["event"], "50")


if __name__ == "__main__":
    unittest.main()
