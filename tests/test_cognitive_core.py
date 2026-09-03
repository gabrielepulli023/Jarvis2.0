import json
import unittest
from types import SimpleNamespace

import cognitive_core


class _Responses:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payloads.pop(0), ensure_ascii=False))


class CognitiveCoreTests(unittest.TestCase):
    def test_complex_request_enters_mission_mode(self):
        self.assertTrue(cognitive_core.mission_required("Crea un progetto completo, testalo e correggi ogni errore"))
        self.assertFalse(cognitive_core.mission_required("apri Chrome"))

    def test_planner_produces_verifiable_plan(self):
        responses = _Responses([{
            "goal": "Creare applicazione",
            "success_criteria": ["Test superati"],
            "steps": [{"id": "s1", "label": "Creare file", "status": "pending", "proof": "File presenti"}],
            "risks": [],
        }])
        plan = cognitive_core.plan_mission(SimpleNamespace(responses=responses), "test-model", "Crea app")
        self.assertEqual(plan["source"], "planner")
        self.assertEqual(plan["success_criteria"], ["Test superati"])

    def test_critic_rejects_missing_evidence(self):
        responses = _Responses([{
            "complete": False,
            "confidence": 0.9,
            "missing": ["Mancano i test"],
            "next_action": "Esegui test_project",
            "summary": "Missione incompleta",
        }])
        review = cognitive_core.review_mission(
            SimpleNamespace(responses=responses), "test-model", "Crea app", {},
            [{"tool": "create_project", "success": True, "message": "creato", "verification": {"status": "verified"}}],
            "Fatto",
        )
        self.assertFalse(review["complete"])
        self.assertIn("Mancano i test", review["missing"])


if __name__ == "__main__":
    unittest.main()
