import sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_memory import MemoryStore
from jarvis_skills import Capability,SkillManifest,SkillRegistry,SkillResult
from jarvis_skills.applications import register_application_skills

class _Processes:
    def __init__(self):self.commands=[]
    def start(self,command,**kwargs):
        self.commands.append(command);process=types.SimpleNamespace(pid=42,poll=lambda:0)
        return types.SimpleNamespace(process=process)

class ApplicationSkillTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="jarvis_apps_"));self.memory=MemoryStore(self.root/"memory.db");self.processes=_Processes();self.registry=SkillRegistry(self.root/"metrics.db",lambda capability:True)
        self.registry.register(SkillManifest("browser.dom","1","dom",("dom",),frozenset({Capability.BROWSER_CONTROL}),"test:dom"),lambda **kwargs:SkillResult(True,"verified",{"verified":True,"arguments":kwargs},"browser.dom"))
        self.registry.register(SkillManifest("browser.snapshot","1","snap",("snap",),frozenset({Capability.BROWSER_CONTROL}),"test:snap"),lambda:SkillResult(True,"snapshot",{"title":"TradingView EURUSD 1h","url":"https://tradingview.com/chart"},"browser.snapshot"))
        register_application_skills(self.registry,self.processes,self.memory,self.root)
    def test_youtube_search_uses_verified_dom_skill(self):
        result=self.registry.execute("youtube.search",query="test video");self.assertTrue(result.success);self.assertIn("search_query=test+video",result.data["arguments"]["target"])
    def test_vscode_opens_only_existing_project(self):
        project=self.root/"project";project.mkdir()
        with patch("jarvis_skills.applications.shutil.which",return_value="code.cmd"):result=self.registry.execute("vscode.open_project",project=str(project))
        self.assertTrue(result.success);self.assertEqual(self.processes.commands[0][-1],str(project))
        self.assertFalse(self.registry.execute("vscode.open_project",project=str(self.root/"missing")).success)
    def test_trading_snapshot_is_observation_only(self):
        result=self.registry.execute("tradingview.snapshot");self.assertTrue(result.success);self.assertIn("EURUSD",result.data["text"])
    def test_trading_analysis_is_saved_as_advisory_episode(self):
        module=types.ModuleType("trading_analyst");module.analyze_trading_chart=lambda question:{"successo":True,"messaggio":"Trend laterale, nessun ordine."}
        with patch.dict(sys.modules,{"trading_analyst":module}):result=self.registry.execute("tradingview.analyze",question="analizza")
        self.assertTrue(result.success);rows=self.memory.search("Trend laterale",kind="episodic");self.assertTrue(rows[0]["metadata"]["advisory_only"])

    def test_football_analysis_requires_authorized_bookmaker_context(self):
        result = self.registry.execute("football.analyze")
        self.assertFalse(result.success)
        self.assertIn("Snai", result.message)

if __name__=="__main__":unittest.main()
