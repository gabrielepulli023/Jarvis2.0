import json,tempfile,unittest
from pathlib import Path
from jarvis_core.events import EventBus
from jarvis_plugins import PluginManager
from jarvis_skills import Capability,SkillManifest,SkillRegistry

class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="jarvis_plugins_"));self.registry=SkillRegistry(self.root/"metrics.db",lambda capability:True)
        self.registry.register(SkillManifest("demo.read","1","read",("read",),frozenset({Capability.READ_FILES}),"demo:read"),lambda value="ok":{"success":True,"message":value})
        self.bus=EventBus();self.manager=PluginManager(self.registry,self.bus,history_limit=16)
    def tearDown(self):self.manager.close()
    def write(self,data):
        folder=self.root/str(data.get("name","plugin"));folder.mkdir(exist_ok=True);path=folder/"plugin.json";path.write_text(json.dumps(data),encoding="utf-8");return path
    @staticmethod
    def valid():return {"name":"demo","version":"1","permissions":["READ_FILES"],"tools":[{"name":"read","skill":"demo.read","permissions":["READ_FILES"],"risk":"safe"}],"events":["demo.changed"]}
    def test_load_execute_and_observe_declared_event(self):
        self.manager.load(self.write(self.valid()));self.assertTrue(self.manager.execute("demo","read",value="done").success);self.bus.publish("demo.changed",source="test")
        snapshot=self.manager.snapshot();self.assertEqual(snapshot["plugins"][0]["name"],"demo");self.assertEqual(snapshot["events"][0]["topic"],"demo.changed")
    def test_rejects_unknown_skill(self):
        data=self.valid();data["tools"][0]["skill"]="missing"
        with self.assertRaisesRegex(ValueError,"inesistente"):self.manager.load(self.write(data))
    def test_rejects_permission_escalation_and_risk_downgrade(self):
        data=self.valid();data["tools"][0]["permissions"]=[]
        with self.assertRaisesRegex(ValueError,"insufficienti"):self.manager.load(self.write(data))
        self.registry.register(SkillManifest("demo.danger","1","danger",("danger",),frozenset({Capability.READ_FILES}),"demo:danger",risk="sensitive"),lambda:{"success":True})
        data=self.valid();data["tools"][0]["skill"]="demo.danger"
        with self.assertRaisesRegex(ValueError,"riduce il rischio"):self.manager.load(self.write(data))
    def test_repository_manifests_are_loaded(self):
        from jarvis_core.runtime import RUNTIME
        names={row["name"] for row in RUNTIME.plugins.snapshot()["plugins"]}
        self.assertEqual(
            names,
            {"chrome", "vscode", "spotify", "tradingview", "file_explorer", "windows_settings", "football"},
        )

if __name__=="__main__":unittest.main()
