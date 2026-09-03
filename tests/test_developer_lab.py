import sys,tempfile,unittest
from pathlib import Path
from jarvis_developer import DeveloperService,LabWorkspace,PatchTransaction,RepositoryAnalyzer,TestRunner

class LabTests(unittest.TestCase):
    def setUp(self):self.base=Path(tempfile.mkdtemp(prefix="jarvis_lab_test_"));self.live=self.base/"live";self.live.mkdir();(self.live/"app.py").write_text("VALUE = 1\n",encoding="utf-8");self.lab=LabWorkspace(self.live,self.base/"labs",self.base/"transactions")
    def test_lab_is_isolated_and_transaction_rolls_back(self):
        lab_root=self.lab.create();transaction=self.lab.transaction();transaction.write("app.py","VALUE = 2\n");transaction.write("new.py","NEW = True\n")
        self.assertEqual((self.live/"app.py").read_text(),"VALUE = 1\n");transaction.rollback();self.assertEqual((lab_root/"app.py").read_text(),"VALUE = 1\n");self.assertFalse((lab_root/"new.py").exists())
    def test_rejects_path_escape(self):
        self.lab.create();transaction=self.lab.transaction()
        with self.assertRaises(ValueError):transaction.write("../escape.py","bad")
    def test_promotes_only_after_validation_and_restores_committed(self):
        self.lab.create();transaction=self.lab.transaction();transaction.write("app.py","VALUE = 3\n");transaction.commit()
        rejected=self.lab.promote(["app.py"],lambda root:{"successo":False});self.assertFalse(rejected["successo"]);self.assertEqual((self.live/"app.py").read_text(),"VALUE = 1\n")
        promoted=self.lab.promote(["app.py"],lambda root:{"successo":True});self.assertTrue(promoted["successo"]);self.assertEqual((self.live/"app.py").read_text(),"VALUE = 3\n")
        tx_dir=self.base/"transactions"/"live"/promoted["transaction"]["id"];PatchTransaction.restore_committed(self.live,tx_dir);self.assertEqual((self.live/"app.py").read_text(),"VALUE = 1\n")

class RepositoryToolsTests(unittest.TestCase):
    def test_analyzer_maps_symbols_entrypoint_and_syntax(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_repo_"));(root/"main.py").write_text("import os\ndef run(): pass\nif __name__ == '__main__': run()\n",encoding="utf-8");(root/"bad.py").write_text("def broken(:\n",encoding="utf-8")
        report=RepositoryAnalyzer(root).analyze();self.assertEqual(report["summary"]["syntax_issues"],1);self.assertIn("main.py",report["entrypoints"]);self.assertEqual(report["modules"][0]["symbols"][0]["name"],"run")
    def test_runner_executes_real_unittest_in_isolation(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_runner_"));(root/"tests").mkdir();(root/"tests"/"test_ok.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",encoding="utf-8")
        result=TestRunner(Path(sys.executable)).run_unittest(root,timeout=10);self.assertTrue(result["successo"]);self.assertIn("OK",result["stderr"])

class DeveloperServiceTests(unittest.TestCase):
    def test_full_lab_patch_test_promote_and_rollback(self):
        base=Path(tempfile.mkdtemp(prefix="jarvis_dev_service_"));live=base/"live";live.mkdir();(live/"tests").mkdir();(live/"app.py").write_text("VALUE=1\n",encoding="utf-8");(live/"tests"/"test_app.py").write_text("import unittest\nfrom app import VALUE\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE,2)\n",encoding="utf-8")
        service=DeveloperService(live,base/"data",Path(sys.executable));lab=service.create_lab();self.assertTrue(service.patch(lab["id"],[{"path":"app.py","content":"VALUE=2\n"}])["successo"]);self.assertTrue(service.test(lab["id"],10)["successo"])
        promoted=service.promote(lab["id"],["app.py"],10);self.assertTrue(promoted["successo"]);self.assertEqual((live/"app.py").read_text(),"VALUE=2\n")
        identity=promoted["transaction"]["id"];self.assertTrue(service.rollback_live(identity)["successo"]);self.assertEqual((live/"app.py").read_text(),"VALUE=1\n")

if __name__=="__main__":unittest.main()
