import tempfile,unittest
from pathlib import Path
from jarvis_skills import Capability,SkillManifest,SkillRegistry

class SkillAuditTests(unittest.TestCase):
    def test_execution_emits_complete_audit_schema(self):
        rows=[];registry=SkillRegistry(Path(tempfile.mkdtemp())/"metrics.db",lambda capability:True,audit=lambda **row:rows.append(row))
        registry.register(SkillManifest("x","1","demo",("x",),frozenset({Capability.READ_FILES}),"demo:x",verification_strategy="observed"),lambda value:{"success":True,"data":{"value":value}})
        self.assertTrue(registry.execute("x",value=3).success);self.assertEqual(len(rows),1)
        self.assertTrue({"request_id","user_command","planner_decision","tool","arguments","risk","permission","result","duration_ms","verification"}<=rows[0].keys());self.assertEqual(rows[0]["verification"],"observed")

if __name__=="__main__":unittest.main()
