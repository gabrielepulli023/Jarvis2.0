import json
import tempfile
import unittest
import sys
from pathlib import Path
from jarvis_skills import Capability,SkillManifest,SkillRegistry,SkillResult
from jarvis_skills.builtin import register_builtin_skills
from jarvis_core.events import EventBus
from jarvis_core.processes import ProcessManager

class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="jarvis_skills_"));self.allowed=set();self.registry=SkillRegistry(self.root/"metrics.db",lambda capability:capability in self.allowed)
    def manifest(self,name="files",fallbacks=()):return SkillManifest(name,"1.0.0","File skill",("read file",),frozenset({Capability.READ_FILES}),f"{name}:run",fallbacks=fallbacks)
    def test_denies_missing_capability_without_execution(self):
        calls=[];self.registry.register(self.manifest(),lambda **kwargs:(calls.append(1) or {"successo":True}))
        result=self.registry.execute("files",path="x");self.assertFalse(result.success);self.assertFalse(calls);self.assertIn("READ_FILES",result.message)
    def test_executes_and_records_metrics(self):
        self.allowed.add(Capability.READ_FILES);self.registry.register(self.manifest(),lambda **kwargs:{"successo":True,"messaggio":"ok","dati":{"path":kwargs["path"]}})
        result=self.registry.execute("files",path="x");self.assertTrue(result.success);self.assertEqual(result.data["path"],"x");self.assertEqual(self.registry.metrics()[0]["successes"],1)
    def test_fallback_is_real_and_measured(self):
        self.allowed.add(Capability.READ_FILES);self.registry.register(self.manifest("primary",("secondary",)),lambda **kwargs:SkillResult(False,"failed",skill="primary"));self.registry.register(self.manifest("secondary"),lambda **kwargs:SkillResult(True,"ok",skill="secondary"))
        result=self.registry.execute("primary");self.assertTrue(result.success);self.assertEqual(result.fallback_used,"secondary");self.assertEqual(len(self.registry.metrics()),2)
    def test_fallback_cannot_escalate_permissions(self):
        primary=SkillManifest("primary","1","p",("p",),frozenset({Capability.READ_FILES}),"p",fallbacks=("danger",))
        danger=SkillManifest("danger","1","d",("d",),frozenset({Capability.SYSTEM_SETTINGS}),"d")
        self.allowed.add(Capability.READ_FILES);calls=[];self.registry.register(primary,lambda:SkillResult(False,"no"));self.registry.register(danger,lambda:(calls.append(1) or SkillResult(True,"yes")))
        result=self.registry.execute("primary");self.assertFalse(result.success);self.assertFalse(calls)
    def test_loads_and_validates_manifest(self):
        directory=self.root/"demo";directory.mkdir();(directory/"skill.json").write_text(json.dumps({"name":"demo","version":"1.0","description":"demo","intents":["demo"],"permissions":["READ_FILES"],"entrypoint":"demo:run","requirements":[],"tests":[],"fallbacks":[]}),encoding="utf-8")
        self.assertEqual(self.registry.load_manifests(self.root),["demo"]);self.assertEqual(self.registry.list()[0]["name"],"demo")
        row=self.registry.list()[0];self.assertEqual(row["risk"],"safe");self.assertEqual(row["timeout"],30);self.assertEqual(row["verification_strategy"],"handler_result")
    def test_manifest_retries_are_bounded_and_measured(self):
        self.allowed.add(Capability.READ_FILES);calls=[]
        manifest=SkillManifest("retry","1","r",("r",),frozenset({Capability.READ_FILES}),"r",retries=2)
        self.registry.register(manifest,lambda:(calls.append(1) or {"successo":len(calls)>=3}))
        self.assertTrue(self.registry.execute("retry").success);self.assertEqual(len(calls),3);self.assertEqual(self.registry.metrics()[0]["uses"],3)
    def test_invalid_manifest_policy_is_rejected(self):
        with self.assertRaises(ValueError):SkillManifest("x","1","x",("x",),frozenset(),"x",risk="root")
    def test_sensitive_skill_requires_unforgeable_staged_confirmation(self):
        allowed={Capability.READ_FILES};registry=SkillRegistry(self.root/"risk.db",lambda capability:capability in allowed,lambda manifest:"confirm" if manifest.risk=="sensitive" else "allow")
        calls=[];registry.register(SkillManifest("x","1","x",("x",),frozenset({Capability.READ_FILES}),"x",risk="sensitive"),lambda value:(calls.append(value) or {"successo":True}))
        staged=registry.execute("x",value=7);self.assertFalse(staged.success);self.assertFalse(calls)
        confirmed=registry.confirm(staged.data["action_id"]);self.assertTrue(confirmed.success);self.assertEqual(calls,[7])
        self.assertFalse(registry.confirm(staged.data["action_id"]).success)
    def test_capability_confirmation_is_not_denial_and_creates_one_pending(self):
        registry = SkillRegistry(self.root / "capability_confirm.db", lambda _capability: "confirm")
        calls = []
        registry.register(
            SkillManifest("settings", "1", "settings", ("settings",), frozenset({Capability.SYSTEM_SETTINGS}), "settings"),
            lambda: calls.append(True) or {"success": True, "message": "ok"},
        )
        staged = registry.execute("settings")
        self.assertFalse(staged.success)
        self.assertTrue(staged.data["requires_confirmation"])
        self.assertEqual(1, len(registry.pending()))
        self.assertTrue(registry.confirm(staged.data["action_id"]).success)
        self.assertEqual([True], calls)

    def test_capability_deny_still_blocks_execution(self):
        registry = SkillRegistry(self.root / "capability_deny.db", lambda _capability: "deny")
        calls = []
        registry.register(self.manifest("settings"), lambda: calls.append(True) or {"success": True})
        result = registry.execute("settings")
        self.assertFalse(result.success)
        self.assertIn("READ_FILES", result.message)
        self.assertFalse(calls)
    def test_forbidden_skill_cannot_be_confirmed(self):
        registry=SkillRegistry(self.root/"forbidden.db",lambda capability:True,lambda manifest:"deny")
        registry.register(SkillManifest("x","1","x",("x",),frozenset(),"x",risk="forbidden"),lambda:{"successo":True})
        self.assertFalse(registry.execute("x").success)
    def test_builtin_file_and_terminal_skills_are_real(self):
        registry=SkillRegistry(self.root/"builtin.db",lambda capability:True);processes=ProcessManager(EventBus());register_builtin_skills(registry,self.root,processes)
        target=self.root/"note.txt";written=registry.execute("files.write",path=str(target),content="hello")
        self.assertTrue(written.success);self.assertEqual(registry.execute("files.read",path=str(target)).data["content"],"hello")
        process=registry.execute("terminal.run",command=[sys.executable,"--version"]);self.assertTrue(process.success);self.assertIn("Python",process.data["stdout"])
        processes.shutdown()
    def test_builtin_file_skill_rejects_workspace_escape(self):
        registry=SkillRegistry(self.root/"escape.db",lambda capability:True);register_builtin_skills(registry,self.root,ProcessManager(EventBus()))
        result=registry.execute("files.read",path=str(self.root.parent/"outside.txt"));self.assertFalse(result.success);self.assertIn("PermissionError",result.message)

if __name__=="__main__":unittest.main()
