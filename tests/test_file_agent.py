import tempfile
import unittest
from pathlib import Path

from jarvis_files import FileAgent, FileOperation


class FileAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.agent = FileAgent([self.root], self.root / ".transactions", massive_threshold=3)
    def tearDown(self): self.temp.cleanup()

    def test_delete_requires_confirmation_and_can_be_rolled_back(self):
        source = self.root / "important.txt"; source.write_text("data", encoding="utf-8")
        plan = self.agent.plan([FileOperation("delete", source=str(source))])
        self.assertTrue(plan.confirmation_required)
        self.assertFalse(self.agent.execute(plan).success); self.assertTrue(source.exists())
        result = self.agent.execute(plan, confirmed=True)
        self.assertTrue(result.success); self.assertFalse(source.exists())
        self.assertTrue(self.agent.rollback(plan.id).success); self.assertEqual(source.read_text(encoding="utf-8"), "data")

    def test_failed_plan_rolls_back_completed_steps(self):
        created = self.root / "new.txt"; missing = self.root / "missing.txt"
        plan = self.agent.plan([FileOperation("write", target=str(created), content="new"), FileOperation("delete", source=str(missing))])
        result = self.agent.execute(plan, confirmed=True)
        self.assertFalse(result.success); self.assertTrue(result.rolled_back); self.assertFalse(created.exists())

    def test_massive_plan_requires_confirmation_and_paths_are_guarded(self):
        operations = [FileOperation("write", target=str(self.root / f"{index}.txt"), content="x") for index in range(3)]
        self.assertTrue(self.agent.plan(operations).confirmation_required)
        with self.assertRaises(PermissionError): self.agent.plan([FileOperation("write", target=str(self.root.parent / "escape.txt"), content="x")])

    def test_dry_run_has_no_side_effects(self):
        target = self.root / "dry.txt"; plan = self.agent.plan([FileOperation("write", target=str(target), content="x")])
        self.assertTrue(self.agent.execute(plan, dry_run=True).success); self.assertFalse(target.exists())


if __name__ == "__main__": unittest.main()
