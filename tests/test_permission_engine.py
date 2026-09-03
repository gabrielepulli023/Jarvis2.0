import unittest

from permission_engine import PermissionEngine, RiskClassifier, RiskLevel


class PermissionEngineTests(unittest.TestCase):
    def setUp(self):
        self.classifier = RiskClassifier()
        self.engine = PermissionEngine()

    def test_safe_action_can_run_without_confirmation(self):
        policy = self.classifier.classify("apri_programma")
        self.assertEqual(policy.risk, RiskLevel.SAFE)
        self.assertEqual(self.engine.evaluate(policy, "allow"), "allow")

    def test_destructive_action_requires_confirmation_even_when_category_allows(self):
        policy = self.classifier.classify("elimina")
        self.assertEqual(policy.risk, RiskLevel.DESTRUCTIVE)
        self.assertEqual(self.engine.evaluate(policy, "allow"), "confirm")
        self.assertEqual(self.engine.evaluate(policy, "allow", confirmed=True), "allow")

    def test_forbidden_action_cannot_be_confirmed(self):
        policy = self.classifier.classify("disable_permission_engine")
        self.assertEqual(self.engine.evaluate(policy, "allow", confirmed=True), "deny")


if __name__ == "__main__":
    unittest.main()
