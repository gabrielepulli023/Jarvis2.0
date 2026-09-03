import json,tempfile,unittest
from pathlib import Path
from jarvis_core.config import ConfigManager

class ConfigDirectoryTests(unittest.TestCase):
    def test_directory_layers_are_deterministic_and_deep_merged(self):
        root=Path(tempfile.mkdtemp());(root/"a.json").write_text(json.dumps({"nested":{"a":1},"x":1}));(root/"b.json").write_text(json.dumps({"nested":{"b":2},"x":2}))
        config=ConfigManager({"nested":{"base":0}},root);self.assertEqual(config.get("nested"),{"base":0,"a":1,"b":2});self.assertEqual(config.get("x"),2)
    def test_repository_configuration_is_loadable(self):
        config=ConfigManager({},Path("config"));self.assertTrue(config.get("watchdog_enabled"));self.assertTrue(config.get("voice")["stt_streaming"]);self.assertTrue(config.get("permissions")["default_deny_unknown"])

    def test_corrupt_optional_layer_does_not_block_other_layers(self):
        root=Path(tempfile.mkdtemp());(root/"a.json").write_text("{broken", encoding="utf-8");(root/"b.json").write_text(json.dumps({"ready":True}), encoding="utf-8")
        config=ConfigManager({"default":True},root)
        self.assertTrue(config.get("default"));self.assertTrue(config.get("ready"))

if __name__=="__main__":unittest.main()
