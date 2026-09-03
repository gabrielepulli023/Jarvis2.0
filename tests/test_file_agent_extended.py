import tempfile,unittest,zipfile
from pathlib import Path
from jarvis_files import FileAgent,FileOperation

class FileAgentExtendedTests(unittest.TestCase):
    def setUp(self):self.root=Path(tempfile.mkdtemp());self.agent=FileAgent([self.root],self.root/"transactions",massive_threshold=3)
    def test_plan_is_retained_dry_run_and_execution_are_separate(self):
        target=self.root/"note.txt";plan=self.agent.plan([FileOperation("write",target=str(target),content="hello")])
        self.assertTrue(self.agent.execute_plan(plan.id,dry_run=True).success);self.assertFalse(target.exists())
        self.assertTrue(self.agent.execute_plan(plan.id,confirmed=True).success);self.assertEqual(target.read_text(),"hello")
    def test_metadata_checksum_compare_archive_and_extract(self):
        first=self.root/"a.txt";second=self.root/"b.txt";first.write_text("same");second.write_text("same")
        self.assertTrue(self.agent.compare(first,second)["equal"]);self.assertEqual(self.agent.metadata(first)["size"],4)
        archive=self.root/"files.zip";self.assertTrue(self.agent.archive([str(first),str(second)],str(archive))["success"]);self.assertEqual(self.agent.inspect_archive(str(archive))["count"],2)
        output=self.root/"out";self.assertTrue(self.agent.extract(str(archive),str(output))["success"]);self.assertEqual((output/"a.txt").read_text(),"same")
    def test_zip_slip_is_rejected_and_destination_removed(self):
        archive=self.root/"bad.zip"
        with zipfile.ZipFile(archive,"w") as value:value.writestr("../escape.txt","bad")
        output=self.root/"out"
        with self.assertRaises(ValueError):self.agent.extract(str(archive),str(output))
        self.assertFalse(output.exists());self.assertFalse((self.root.parent/"escape.txt").exists())

if __name__=="__main__":unittest.main()
